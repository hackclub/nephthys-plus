import logging

from slack_sdk.web.async_client import AsyncWebClient

from nephthys.database.tables import Ticket
from nephthys.utils import ai_help

DISCLAIMER = (
    "_DISCLAIMER: this is a beta feature. this is an llm and may make mistakes. "
    "check important information. a helper will come by soon to confirm._"
)

# Thread timestamps that have an AI answer in progress or already posted.
# Guards against repeated presses of the "BETA ask ai" button.
_claimed_threads: set[str] = set()


async def ask_ai(
    channel: str, thread_ts: str, user_id: str, client: AsyncWebClient
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

    if thread_ts in _claimed_threads:
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            thread_ts=thread_ts,
            text="The AI has already answered this question (or is answering it now).",
        )
        return False
    _claimed_threads.add(thread_ts)

    try:
        text = await ai_help.answer(channel, thread_ts)
    except Exception:
        _claimed_threads.discard(thread_ts)  # allow a retry after a failure
        logging.exception(f"AI help failed for thread_ts={thread_ts}")
        await client.chat_postEphemeral(
            channel=channel,
            user=user_id,
            thread_ts=thread_ts,
            text="Sorry, the AI couldn't answer that. A helper will be along soon!",
        )
        return False

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"{DISCLAIMER}\n\n{text}",
        unfurl_links=False,
        unfurl_media=False,
    )
    return True
