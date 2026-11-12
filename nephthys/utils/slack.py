import logging
import re
from typing import Any
from typing import Dict

from blockkit import Input
from blockkit import Modal
from blockkit import Option
from blockkit import PlainTextInput
from blockkit import Section
from blockkit import StaticSelect
from slack_bolt.async_app import AsyncApp
from slack_bolt.context.ack.async_ack import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.actions.ask_ai import ask_ai
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
from nephthys.actions.tag_subscribe import tag_subscribe_callback
from nephthys.database.enums import FeedbackRating
from nephthys.database.tables import Feedback
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.errors.errors import PermissionDenied
from nephthys.errors.errors import TicketNotClosedError
from nephthys.events.app_home_opened import on_app_home_opened
from nephthys.events.app_home_opened import open_app_home
from nephthys.events.channel_join import channel_join
from nephthys.events.channel_left import channel_left
from nephthys.events.message_creation import get_forwarded_ticket_user
from nephthys.events.message_creation import on_message
from nephthys.events.message_deletion import on_message_deletion
from nephthys.options.category_tags import get_category_tags
from nephthys.options.team_tags import get_team_tags
from nephthys.utils.env import env
from nephthys.utils.nps import rating_for
from nephthys.utils.nps import update_nps_anchor
from nephthys.utils.performance import perf_timer
from nephthys.utils.ticket_methods import get_question_message_link
from nephthys.views.home import AppHomeView

app = AsyncApp(token=env.slack_bot_token, signing_secret=env.slack_signing_secret)


@app.event("message")
async def handle_message(event: Dict[str, Any], client: AsyncWebClient):
    logging.debug(f"Message event: {event}")
    is_message_deletion = (
        event.get("subtype") == "message_changed"
        and event["message"].get("subtype") == "tombstone"
    ) or event.get("subtype") == "message_deleted"

    if event["channel"] == env.slack_help_channel or get_forwarded_ticket_user(event):
        async with perf_timer("Processing message event (total time)"):
            if is_message_deletion:
                await on_message_deletion(event, client)
            else:
                await on_message(event, client)


@app.event("message_metadata_posted")
async def handle_message_metadata_posted(event: Dict[str, Any], client: AsyncWebClient):
    channel = event["channel_id"]
    ts = event["message_ts"]
    history = await client.conversations_history(
        channel=channel, latest=ts, inclusive=True, limit=1
    )
    messages = history.get("messages") or []
    if not messages or messages[0].get("ts") != ts:
        return
    forwarded = {**messages[0], "channel": channel, "metadata": event["metadata"]}
    if channel == env.slack_help_channel and get_forwarded_ticket_user(forwarded):
        await on_message(forwarded, client)


@app.action("mark_resolved")
async def handle_mark_resolved_button(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await ack()
    value = body["actions"][0]["value"]
    resolver = body["user"]["id"]
    await resolve(value, resolver, client)


@app.action("ask_ai")
async def handle_ask_ai_button(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await ack()
    channel = body["channel"]["id"]
    thread_ts = body["actions"][0]["value"]
    answered = await ask_ai(
        channel=channel,
        thread_ts=thread_ts,
        user_id=body["user"]["id"],
        team_id=body["team"]["id"],
        client=client,
    )
    if answered:
        # Slack buttons can't be disabled, so drop the button from the message.
        message = body.get("message", {})
        blocks = []
        for block in message.get("blocks", []):
            if block.get("type") == "actions":
                block = {
                    **block,
                    "elements": [
                        el
                        for el in block.get("elements", [])
                        if el.get("action_id") != "ask_ai"
                    ],
                }
                if not block["elements"]:
                    continue
            blocks.append(block)
        await client.chat_update(
            channel=channel,
            ts=message.get("ts", thread_ts),
            text=message.get("text", ""),
            blocks=blocks,
        )


@app.options("tag-list")  # compat with old backend msgs
@app.options("team-tag-list")
async def handle_team_tag_list_options(ack: AsyncAck, payload: dict):
    tags = await get_team_tags(payload)
    await ack(options=tags)


@app.options("category-tag-list")
async def handle_category_tag_list_options(ack: AsyncAck, payload: dict):
    tags = await get_category_tags(payload)
    await ack(options=tags)


@app.event("app_home_opened")
async def app_home_opened_handler(event: dict[str, Any], client: AsyncWebClient):
    await on_app_home_opened(event, client)


async def manage_home_switcher(ack: AsyncAck, body, client: AsyncWebClient):
    await ack()
    user_id = body["user"]["id"]
    action_id = body["actions"][0]["action_id"]
    try:
        view = AppHomeView(action_id)
    except ValueError:
        logging.error(
            f"Invalid app home view requested user_id={user_id} action_id={action_id}"
        )
        return

    await open_app_home(view, client, user_id)


for view in AppHomeView:
    app.action(view.id)(manage_home_switcher)


@app.action(re.compile(r"assigned-tickets-page-\d+"))
async def handle_assigned_tickets_page(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await ack()
    user_id = body["user"]["id"]
    page = int(body["actions"][0]["action_id"].rsplit("-", 1)[-1])
    await open_app_home(AppHomeView.ASSIGNED_TICKETS, client, user_id, page=page)


@app.event("member_joined_channel")
async def handle_member_joined_channel(event: Dict[str, Any], client: AsyncWebClient):
    await channel_join(ack=AsyncAck(), event=event, client=client)


@app.event("member_left_channel")
async def handle_member_left_channel(event: Dict[str, Any], client: AsyncWebClient):
    await channel_left(ack=AsyncAck(), event=event, client=client)


@app.action("create-team-tag")
async def create_team_tag(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await create_team_tag_btn_callback(ack, body, client)


@app.view("create_team_tag")
async def create_team_tag_view(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await create_team_tag_view_callback(ack, body, client)


@app.action("create-category-tag")
async def create_category_tag(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await create_category_tag_btn_callback(ack, body, client)


@app.view("create_category_tag")
async def create_category_tag_view(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await create_category_tag_view_callback(ack, body, client)


@app.action("edit-category-tag")
async def edit_category_tag(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await edit_category_tag_btn_callback(ack, body, client)


@app.view("edit_category_tag")
async def edit_category_tag_view(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await edit_category_tag_view_callback(ack, body, client)


@app.action("tag-subscribe")
async def tag_subscribe(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await tag_subscribe_callback(ack, body, client)


@app.action("tag-list")  # compat with old backend msgs
@app.action("team-tag-list")
async def assign_team_tag(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await assign_team_tag_callback(ack, body, client)


@app.action("category-tag-list")
async def assign_category_tag(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
):
    await assign_category_tag_callback(ack, body, client)


# Action buttons on the "resolved ticket" message
@app.action("reopen-button")
async def reopen_ticket(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await ack()
    ticket_id = int(body["actions"][0]["value"])
    slack_id = body["user"]["id"]
    if not (ticket := await Ticket.objects().get(Ticket.id == ticket_id)):
        raise ValueError(f"Failed to find ticket ticket_id={ticket_id}")
    if not (reopened_by := await User.objects().get(User.slack_id == slack_id)):
        logging.warning(
            f"User slack_id={slack_id} not in database tried to reopen ticket_id={ticket_id}"
        )
        return
    try:
        await reopen(ticket, reopened_by, client)
    except TicketNotClosedError:
        await client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ticket.msg_ts,
            user=slack_id,
            text="This thread has already been re-opened!",
        )
    except PermissionDenied:
        await client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ticket.msg_ts,
            user=slack_id,
            text="Only helpers or the original poster can reopen their thread.",
        )


@app.action("feedback-button")
async def feedback_button(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    slack_id = body["user"]["id"]
    ticket_id = int(body["actions"][0]["value"])
    if not (ticket := await Ticket.objects().get(Ticket.id == ticket_id)):
        raise ValueError(f"Failed to find ticket ticket_id={ticket_id}")
    user = await User.objects().get(User.slack_id == slack_id)
    if not user or ticket.opened_by != user.id:
        await client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ticket.msg_ts,
            user=slack_id,
            text="Only the original poster can give feedback on this ticket.",
        )
        logging.info(
            f"Ignoring feedback attempt by non-OP. slack_id={slack_id} user_id={user.id if user else None} ticket_id={ticket_id}"
        )
        await ack()
        return

    logging.info(
        f"Opening feedback dialog slack_id={slack_id} user_id={user.id} ticket_id={ticket_id}"
    )
    await ack()
    modal = Modal(
        title="Feedback",
        private_metadata=f"{ticket_id}",
        submit="Submit",
        callback_id="submit-feedback",
        blocks=[
            Input(
                "How likely are you to recommend this help channel to a friend?",
                block_id="rating",
                element=StaticSelect(
                    action_id="rating",
                    placeholder="0 = not at all likely, 10 = extremely likely",
                    options=[Option(str(n), str(n)) for n in range(11)],
                ),
            ),
            Input(
                "Any additional comments?",
                block_id="text",
                optional=True,
                hint="Optionally, give any praise, complaints, or suggestions you have for the help channel",
                element=PlainTextInput(
                    action_id="text",
                    multiline=True,
                ),
            ),
            Section(text=env.transcript.ticket_feedback_text),
        ],
    )
    await client.views_open(view=modal.build(), trigger_id=body["trigger_id"])


@app.view("submit-feedback")
async def submit_feedback(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    slack_id = body["user"]["id"]
    ticket_id = int(body["view"]["private_metadata"])
    form_data = body["view"]["state"]["values"]
    rating_value = form_data["rating"]["rating"]["selected_option"]["value"]
    text = form_data["text"]["text"]["value"]
    logging.info(
        f"Ticket feedback submission ticket_id={ticket_id} slack_id={slack_id}"
    )

    if not (ticket := await Ticket.objects().get(Ticket.id == ticket_id)):
        raise ValueError(f"Failed to find ticket ticket_id={ticket_id}")
    if not (submitted_by := await User.objects().get(User.slack_id == slack_id)):
        raise ValueError(f"Failed to find user with slack_id={slack_id}")
    score = int(rating_value)
    rating = rating_for(score)

    await Feedback.objects().create(
        ticket=ticket, created_by=submitted_by, rating=rating, score=score, text=text
    )

    if env.feedback_channel_id:
        try:
            said = f' said "{text}"' if text else " left feedback"
            await client.chat_postMessage(
                channel=env.feedback_channel_id,
                text=f"<@{slack_id}>{said} ({score}/10) - <{get_question_message_link(ticket)}|thread>",
            )
        except Exception as e:
            logging.error(f"Failed to post feedback to channel: {e!r}")

    # Show a success dialog (customised to the user's feeling and if they gave textual feedback)
    thank_you_text = "Feedback submitted successfully!"
    if text:
        thank_you_text += "\n\nThis goes a long way in helping us make the channel even better, thank you!"
        if rating == FeedbackRating.GREAT:
            thank_you_text += " :yay:"
    if rating is FeedbackRating.NOT_GOOD:
        thank_you_text += "\n\nIf your issue still hasn't been resolved, feel free to re-open the thread and we'll help you further."

    success_modal = Modal(
        title="Feedback",
        close="Close",
        blocks=[Section(text=thank_you_text)],
    )

    await ack(
        response_action="update",
        view=success_modal.build(),
    )
    await update_nps_anchor(repost=True)


@app.action("add-macro")
async def add_macro(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await open_add_macro_modal(ack, body, client)


@app.action("edit-macro")
async def edit_macro(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await open_edit_macro_modal(ack, body, client)


@app.action("delete-macro")
async def delete_macro(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await delete_macro_callback(ack, body, client)


@app.view("macro_form")
async def macro_form(ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient):
    await macro_form_view_callback(ack, body, client)
