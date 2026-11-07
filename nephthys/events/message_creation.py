import logging
import re
from datetime import datetime
from datetime import UTC
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

from nephthys.actions.ai_summary import ai_summary
from nephthys.actions.assign_category_tag import assign_category_tag_callback
from nephthys.actions.assign_team_tag import assign_team_tag_callback
from nephthys.actions.create_category_tag import create_category_tag_btn_callback
from nephthys.actions.create_category_tag import create_category_tag_view_callback
from nephthys.actions.create_team_tag import create_team_tag_btn_callback
from nephthys.actions.create_team_tag import create_team_tag_view_callback
from nephthys.actions.edit_category_tag import edit_category_tag_btn_callback
from nephthys.actions.edit_category_tag import edit_category_tag_view_callback
from nephthys.actions.manage_macros import delete_macro_callback
from nephthys.actions.manage_macros import macro_form_view_callback
from nephthys.actions.manage_macros import open_add_macro_modal
from nephthys.actions.manage_macros import open_edit_macro_modal
from nephthys.actions.reopen import reopen
from nephthys.actions.resolve import resolve
from nephthys.database.enums import FeedbackRating
from nephthys.database.enums import TicketStatus
from nephthys.database.enums import UserType
from nephthys.database.tables import BotMessage
from nephthys.database.tables import CategoryTag
from nephthys.database.tables import Feedback
from nephthys.database.tables import Macro
from nephthys.database.tables import Tag
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.errors.errors import PermissionDenied
from nephthys.errors.errors import TicketNotClosedError
from nephthys.events.channel_join import channel_join
from nephthys.events.channel_left import channel_left
from nephthys.utils.ai import decisions
from nephthys.utils.ai import run_ai_decisions
from nephthys.utils.env import env
from nephthys.utils.performance import perf_timer
from nephthys.utils.permissions import can_resolve
from nephthys.utils.slack_user import get_user_profile
from nephthys.utils.ticket_methods import delete_message
from nephthys.utils.ticket_methods import post_reply
from nephthys.utils.ticket_methods import reply_to_ticket

LOG = logging.getLogger(__name__)

ALLOWED_SUBTYPES = {
    "thread_broadcast",
    "bot_message",
    "message_changed",
    "message_deleted",
}

class ThreadGoneError(Exception):
    pass

async def post_user_facing_message(
    event: dict[str, Any],
    client: AsyncWebClient,
    text: str,
    buttons: list[dict[str, Any]],
    wait_estimate: str | None = None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text},
        },
        {"type": "actions", "elements": buttons},
    ]
    if wait_estimate:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": wait_estimate}],
            }
        )
    response = await client.chat_postMessage(
        channel=event["channel"],
        text=text,
        blocks=blocks,
        thread_ts=event.get("ts"),
        unfurl_links=False,
        unfurl_media=False,
    )
    msg: dict = response["message"]  # type: ignore (assuming it exists)
    msg_ts = msg.get("ts")
    if not msg_ts:
        raise ValueError(f"User-facing message has no ts: {msg}")
    if not msg.get("thread_ts"):
        logging.warning(
            f"User-facing message was sent outside of thread. Attempted to send to thread_ts={event['ts']}. Unsending."
        )
        await client.chat_delete(channel=event["channel"], ts=msg_ts)
        raise ThreadGoneError()
    return msg


def get_forwarded_ticket_user(event: dict[str, Any]) -> str | None:
    metadata = event.get("metadata")
    if not metadata:
        message = event.get("message")
        if isinstance(message, dict):
            metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if metadata.get("event_type") != "nephthys_plus_forward":
        return None
    payload = metadata.get("event_payload")
    if not isinstance(payload, dict) or payload.get("ticket") is not True:
        return None
    source_user_id = payload.get("source_user_id")
    return source_user_id if isinstance(source_user_id, str) else None


def get_message_author_id(event: dict[str, Any]) -> str | None:
    forwarded_user_id = get_forwarded_ticket_user(event)
    if forwarded_user_id:
        return forwarded_user_id
    user_id = event.get("user")
    return user_id if isinstance(user_id, str) else None


async def on_message(event: dict[str, Any], client: AsyncWebClient):
    """
    Handle incoming messages in Slack.
    """
    forwarded_user_id = get_forwarded_ticket_user(event)
    if forwarded_user_id:
        if await Ticket.objects().where(Ticket.msg_ts == event["ts"]).first():
            return
        forwarded_event = {**event, "user": forwarded_user_id}
        db_user = await User.objects().where(User.slack_id == forwarded_user_id).first()
        await handle_new_question(forwarded_event, client, db_user)
        return

    if "subtype" in event and event["subtype"] not in ALLOWED_SUBTYPES:
        return
    if "bot_id" in event and not (event.get("user") and event.get("thread_ts")):
        logging.info(f"Ignoring bot message from {event['bot_id']}")
        return

    maybe_promote(event)

    async with perf_timer("DB user lookup"):
        db_user = (
            await User.objects()
            .where(User.slack_id == event.get("user", "unknown"))
            .first()
        )

    # Messages sent in a thread with the "send to channel" checkbox checked
    if event.get("subtype") == "thread_broadcast" and not (db_user and db_user.helper):
        async with perf_timer("Handling message sent to channel"):
            await handle_message_sent_to_channel(event, client)

    if "thread_ts" not in event:
        if db_user and db_user.helper and not event.get("bot_id"):
            async with perf_timer("Helper direct message"):
                await handle_helper_dm(event, client, db_user)
            return
        async with perf_timer("New question"):
            await handle_new_question(event, client, db_user)
        return

    # Thread replies
    thread_ts = event["thread_ts"]
    async with perf_timer("Thread reply DB lookup"):
        ticket = await Ticket.objects().where(Ticket.msg_ts == thread_ts).first()
    if not ticket:
        return

    # Ignore replies from the original poster if the ticket is already closed
    if ticket.status == TicketStatus.CLOSED and event.get("user") == ticket.opened_by.slack_id:
        return

    if "subtype" in event and event["subtype"] in {"message_changed", "message_deleted"}:
        if event["subtype"] == "message_changed" and "message" in event:
            await handle_message_change(event, client, ticket)
        return

    async with perf_timer("Thread reply processing"):
        await handle_thread_reply(event, client, ticket)


async def handle_new_question(
    event: dict[str, Any],
    client: AsyncWebClient,
    db_user: User | None,
):
    """
    Handle a new top-level message in the help channel.
    """
    user_id = event.get("user")
    if not user_id:
        return

    # Check if this is a forwarded message
    is_forwarded = get_forwarded_ticket_user(event) is not None

    # Get or create the user
    if not db_user:
        profile = await get_user_profile(user_id)
        db_user = await User.objects().get_or_create(
            User.slack_id == user_id, defaults={User.username: profile.username()}
        )

    # Create the ticket
    now = datetime.now(UTC)
    msg_ts = event["ts"]
    ticket_ts = event.get("ticket_ts", msg_ts)
    title = event.get("text", "")[:100]
    description = event.get("text", "")

    ticket = await Ticket.objects().create(
        title=title,
        description=description,
        msg_ts=msg_ts,
        ticket_ts=ticket_ts,
        opened_by=db_user,
        last_msg_by=UserType.AUTHOR,
        last_msg_at=now,
    )

    # Post the initial bot message
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Mark as resolved"},
            "action_id": "mark_resolved",
            "value": str(ticket.id),
            "style": "primary",
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Ask AI"},
            "action_id": "ask_ai",
            "value": msg_ts,
        },
    ]

    if is_forwarded:
        buttons.insert(
            0,
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View original"},
                "action_id": "view_original",
                "value": ticket_ts,
            },
        )

    await post_user_facing_message(event, client, env.transcript.ticket_created, buttons)

    # Create category tags if AI categorization is enabled
    if env.ai_category_tagging:
        await run_ai_decisions(ticket, client)

    logging.info(f"Created ticket {ticket.id} for user {user_id}")


async def handle_thread_reply(
    event: dict[str, Any],
    client: AsyncWebClient,
    ticket: Ticket,
):
    """
    Handle a reply in a ticket thread.
    """
    user_id = event.get("user")
    if not user_id:
        return

    # Get or create the user
    db_user = await User.objects().where(User.slack_id == user_id).first()
    if not db_user:
        profile = await get_user_profile(user_id)
        db_user = await User.objects().get_or_create(
            User.slack_id == user_id, defaults={User.username: profile.username()}
        )

    # Update ticket metadata
    now = datetime.now(UTC)
    await Ticket.update(
        {
            Ticket.last_msg_at: now,
            Ticket.last_msg_by: (
                UserType.HELPER
                if db_user.helper
                else UserType.AUTHOR if user_id == ticket.opened_by.slack_id else UserType.OTHER
            ),
        }
    ).where(Ticket.id == ticket.id)

    # If this is the first helper reply, record it
    if db_user.helper and not ticket.first_reply_at:
        await Ticket.update({Ticket.first_reply_at: now}).where(Ticket.id == ticket.id)

    # Post a reply message
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Mark as resolved"},
            "action_id": "mark_resolved",
            "value": str(ticket.id),
            "style": "primary",
        }
    ]
    await post_user_facing_message(
        event,
        client,
        env.transcript.ticket_reply,
        buttons,
    )

    logging.info(f"Thread reply on ticket {ticket.id} by user {user_id}")


async def handle_message_change(
    event: dict[str, Any],
    client: AsyncWebClient,
    ticket: Ticket,
):
    """
    Handle a message change in a ticket thread.
    """
    # For now, just log it
    logging.info(f"Message changed in ticket {ticket.id}: {event}")


async def handle_helper_dm(
    event: dict[str, Any],
    client: AsyncWebClient,
    db_user: User,
):
    """
    Handle a direct message from a helper.
    """
    # For now, just log it
    logging.info(f"Helper DM from {db_user.slack_id}: {event}")


async def handle_message_sent_to_channel(
    event: dict[str, Any],
    client: AsyncWebClient,
):
    """
    Handle a message sent to channel via the "send to channel" checkbox.
    """
    # For now, just log it
    logging.info(f"Message sent to channel: {event}")
