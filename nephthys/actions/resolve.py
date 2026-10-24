import logging
import re
from datetime import datetime
from datetime import UTC

from blockkit import Actions
from blockkit import Button
from blockkit import Section
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.database.enums import TicketStatus
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.utils.ai import decisions
from nephthys.utils.delete_thread import add_thread_to_delete_queue
from nephthys.utils.env import env
from nephthys.utils.permissions import can_resolve
from nephthys.utils.slack_user import get_user_profile
from nephthys.utils.ticket_methods import delete_message
from nephthys.utils.ticket_methods import reply_to_ticket


CREDIT_INSTRUCTIONS = (
    "Pick who gets credit for helping with this ticket. Choose the person who did the "
    "most to answer or solve the poster's question, judged by the substance of their "
    "replies, not just how many. Each reply has a 'role': 'poster' is the person who "
    "asked; everyone else is a helper or a community member, and community members "
    "are just as eligible as helpers. The poster staying silent, not thanking anyone, "
    "or leaving the channel does NOT mean nobody helped. Ignore replies that add "
    "nothing (thanks, +1, chatter). A redirect, link or pointer to the right resource "
    "(e.g. a form, channel or doc) IS a real answer and deserves credit, even if the "
    "question was about something other than Hack Club support or the poster never "
    "replied. If anyone made a genuine attempt to help a real person, pick them."
)
# Asked separately from the credit choice: offering "no one" alongside the helpers
# pulls probability away from real answers, so it is decided here instead.
JUNK_INSTRUCTIONS = (
    "Default to genuine. Answer junk ONLY if the original post is itself unmistakably "
    "a test, spam, gibberish or a joke. Vague, short, off-topic, mistaken-channel, "
    "advertising, greeting, or poorly worded posts, and posts where a helper replied, "
    "are genuine."
)
# Replies that only manage the thread are not help, so they never count towards credit
HOUSEKEEPING = re.compile(
    r"^\s*\?\w+\s*$"  # macro commands like ?resolve
    r"|marked as resolved"
    r"|(closing|resolving|resolve|close|mark(ing)?)\b.{0,40}\b(this|it|ticket|thread|post)\b"
    r".{0,60}(inactiv|resolved|no (response|activity)|days|old|duplicate)"
    r"|since you last responded|i get it now|has this been solved"
    r"|did (you|u) get (your|ur) answer"
    r"|please (thread|keep everything)|thread your messages",
    re.IGNORECASE,
)
JUNK_CRITERIA = {
    "genuine": "Anything a real person posted hoping for an answer or help, however vague, basic, off-topic or badly asked.",
    "junk": "Unmistakably a test post (e.g. 'test', 'hello test'), spam, gibberish or a joke with no real question.",
}


async def get_or_create_users(slack_ids: set[str]) -> list[User]:
    users = []
    for slack_id in slack_ids:
        user = await User.objects().where(User.slack_id == slack_id).first()
        if not user:
            profile = await get_user_profile(slack_id)
            user = await User.objects().get_or_create(
                User.slack_id == slack_id, defaults={User.username: profile.username()}
            )
        users.append(user)
    return users


async def resolve(
    ts: str,
    resolver: str,
    client: AsyncWebClient,
    stale: bool = False,
    add_reaction: bool = True,
    send_resolved_message: bool = True,
):
    resolving_user = await User.objects().where(User.slack_id == resolver).first()
    if not resolving_user:
        logging.info(
            f"User {resolver} attempted to resolve ticket with ts {ts} but isn't in the database."
        )
        return

    allowed = await can_resolve(resolving_user.slack_id, resolving_user.id, ts)
    if not allowed:
        logging.info(
            f"User {resolver} attempted to resolve ticket with ts {ts} without permission."
        )
        await client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ts,
            user=resolver,
            text="Only helpers or the original poster can mark this thread as resolved.",
        )
        return

    ticket = await Ticket.objects(Ticket.assigned_to, Ticket.opened_by).get(
        (Ticket.msg_ts == ts)
    )
    if not ticket:
        raise ValueError(f"Failed to find ticket with ts {ts}")
    if ticket.status == TicketStatus.CLOSED:
        await client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ticket.msg_ts,
            user=resolver,
            text="Cannot mark as resolved — this ticket is already resolved!",
        )
        return

    now = datetime.now(UTC)
    credit_user = None
    jev_decided = False
    try:
        replies = await env.slack_client.conversations_replies(
            channel=env.slack_help_channel,
            ts=ticket.msg_ts,
            include_all_metadata=True,
            limit=500,
        )
        thread = []
        for msg in (replies["messages"] or [])[1:]:
            metadata = msg.get("metadata") or {}
            author = None
            if metadata.get("event_type") == "nephthys_macro_reply":
                author = (metadata.get("event_payload") or {}).get("source_user_id")
            elif not msg.get("bot_id"):
                author = msg.get("user")
            if author and (
                author == ticket.opened_by.slack_id
                or not HOUSEKEEPING.search(msg.get("text") or "")
            ):
                thread.append({"author": author, "text": msg.get("text") or ""})
        opener = ticket.opened_by
        authors = {m["author"] for m in thread} - {opener.slack_id}
        candidate = await get_or_create_users(authors)
        if not env.credit_non_helpers:
            candidate = [c for c in candidate if c.helper]
        if candidate:
            names = {
                c.slack_id: f"{c.username or c.slack_id} "
                f"({'helper' if c.helper else 'community member'})"
                for c in candidate
            }
            for m in thread:
                m["role"] = (
                    "poster"
                    if m["author"] == opener.slack_id
                    else names.get(m["author"], "non-human")
                )
            credit_user = candidate[0] if len(candidate) == 1 else None
            response = await decisions(
                model=env.ai_credit_model,
                state={
                    "question": {
                        "title": ticket.title,
                        "description": ticket.description,
                    },
                    "replies": thread,
                },
                questions={
                    "kind": {
                        "type": "choice",
                        "instructions": JUNK_INSTRUCTIONS,
                        "criteria": JUNK_CRITERIA,
                    },
                    "credit": {
                        "type": "choice",
                        "instructions": CREDIT_INSTRUCTIONS,
                        "criteria": {
                            c.slack_id: (
                                f"{names[c.slack_id]}: "
                                f"{sum(1 for m in thread if m['author'] == c.slack_id)} replies"
                            )
                            for c in candidate
                        },
                    },
                },
            )
            choice = response["answers"]["credit"]["choice"]
            is_junk = response["answers"]["kind"]["choice"] == "junk"
            credit_user = (
                None
                if is_junk
                else next((c for c in candidate if c.slack_id == choice), None)
            )
            jev_decided = True
    except Exception as e:
        logging.error(f"Failed to pick credit user: {e!r}", exc_info=True)
    await Ticket.update(
        {
            Ticket.status: TicketStatus.CLOSED,
            Ticket.closed_by: credit_user.id if credit_user else None,
            Ticket.closed_at: now,
        }
    ).where(Ticket.msg_ts == ts)

    tkt = await Ticket.objects().where(Ticket.msg_ts == ts).first()
    if not tkt:
        logging.warning(
            f"Failed to resolve ticket with ts {ts} by {resolver}. Ticket not found."
        )
        return

    # Build the "ticket resolved!" message
    text = (
        env.transcript.ticket_resolve.format(user_id=resolving_user.slack_id)
        if not stale
        else env.transcript.ticket_resolve_stale.format(user_id=resolving_user.slack_id)
    )
    actions = Actions()
    if env.enable_feedback:
        actions.add_element(
            Button(
                text="Give feedback",
                action_id="feedback-button",
                value=f"{tkt.id}",
            )
        )
    actions.add_element(
        Button(
            text="Re-open thread",
            action_id="reopen-button",
            value=f"{tkt.id}",
        )
    )

    if send_resolved_message:
        await reply_to_ticket(
            ticket=tkt,
            client=client,
            text=text,
            blocks=[Section(text), actions],
        )
    if jev_decided and resolving_user.helper:
        if credit_user is None:
            note = "Jev :tm: decided that no one gets credit for this one."
        elif credit_user.slack_id != resolving_user.slack_id:
            note = f"nice try stealing that ticket, but Jev :tm: decided that <@{credit_user.slack_id}> will get the credit."
        else:
            note = None
        if note:
            await client.chat_postEphemeral(
                channel=env.slack_help_channel,
                thread_ts=ts,
                user=resolving_user.slack_id,
                text=note,
            )
    if add_reaction:
        await client.reactions_add(
            channel=env.slack_help_channel,
            name="white_check_mark",
            timestamp=ts,
        )

    try:
        await client.reactions_remove(
            channel=env.slack_help_channel,
            name="thinking_face",
            timestamp=ts,
        )
    except SlackApiError as e:
        logging.error(
            f"Failed to remove thinking reaction from ticket with ts {ts}: {e.response['error']}"
        )

    if await env.workspace_admin_available():
        await add_thread_to_delete_queue(
            channel_id=env.slack_ticket_channel, thread_ts=tkt.ticket_ts
        )
    else:
        await delete_message(
            channel_id=env.slack_ticket_channel, message_ts=tkt.ticket_ts
        )

    logging.info(
        f"Resolved ticket ts={ts} by slack_id={resolving_user.slack_id} credit_to={credit_user.slack_id if credit_user else None}"
    )
