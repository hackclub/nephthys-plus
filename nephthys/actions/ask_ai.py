import logging

from slack_sdk.models.messages.chunk import MarkdownTextChunk
from slack_sdk.models.messages.chunk import TaskUpdateChunk
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.database.tables import Ticket
from nephthys.utils import ai_help

DISCLAIMER = (
    "_DISCLAIMER: this is a beta feature. this is an llm and may make mistakes. "
    "check important information. a helper will come by soon to confirm._"
)

_running: set[str] = set()
_last_seen: dict[str, str] = {}


async def ask_ai(
    channel: str, thread_ts: str, user_id: str, team_id: str, client: AsyncWebClient
) -> bool:
    """Post an AI answer in the thread. Returns True if an answer was posted."""
    ticket = (
        await Ticket.objects(Ticket.opened_by).where(Ticket.msg_ts == thread_ts).first()
    )
    if not ticket or ticket.opened_by.slack_id != user_id:
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            thread_ts=thread_ts,
            text="Only the person who asked the question can use this button.",
        )
        return False

    if thread_ts in _running:
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            thread_ts=thread_ts,
            text="The AI is answering this question right now.",
        )
        return False
    if thread_ts in _last_seen:
        replies = await client.conversations_replies(channel=channel, ts=thread_ts)
        if replies["messages"][-1]["ts"] <= _last_seen[thread_ts]:
            await client.chat_postEphemeral(
                channel=channel,
                user=user_id,
                thread_ts=thread_ts,
                text="Nothing new in the thread since the AI last answered. Reply first, then ask again.",
            )
            return False
    _running.add(thread_ts)

    stream = await client.chat_stream(
        channel=channel,
        thread_ts=thread_ts,
        recipient_team_id=team_id,
        recipient_user_id=user_id,
    )
    await stream.append(
        chunks=[TaskUpdateChunk(id="think", title="Thinking...", status="in_progress")]
    )
    try:
        text = await ai_help.answer(channel, thread_ts)
    except Exception:
        _running.discard(thread_ts)
        logging.exception(f"AI help failed for thread_ts={thread_ts}")
        await stream.stop(
            chunks=[TaskUpdateChunk(id="think", title="Failed", status="error")]
        )
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            thread_ts=thread_ts,
            text="Sorry, the AI couldn't answer that. A helper will be along soon!",
        )
        return False

    await stream.stop(
        chunks=[
            TaskUpdateChunk(id="think", title="Thought", status="complete"),
            MarkdownTextChunk(text=f"{DISCLAIMER}\n\n{text}"),
        ],
        blocks=[
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "BETA ask AI again"},
                        "action_id": "ask_ai",
                        "value": thread_ts,
                    }
                ],
            }
        ],
    )
    replies = await client.conversations_replies(channel=channel, ts=thread_ts)
    _last_seen[thread_ts] = replies["messages"][-1]["ts"]
    _running.discard(thread_ts)
    return True
