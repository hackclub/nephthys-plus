import asyncio
import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from slack_sdk.errors import SlackApiError

from nephthys.actions.resolve import resolve
from nephthys.database.enums import TicketStatus
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.utils.ai import ai_client
from nephthys.utils.ai import decisions
from nephthys.utils.env import env


async def get_is_stale(ts: str, stale_ticket_days: int, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            replies = await env.slack_client.conversations_replies(
                channel=env.slack_help_channel, ts=ts, limit=1000
            )
            last_reply = (
                replies.get("messages", [])[-1] if replies.get("messages") else None
            )
            if not last_reply:
                logging.error("No replies found - this should never happen")
                return False
            return (
                datetime.now(tz=timezone.utc)
                - datetime.fromtimestamp(float(last_reply["ts"]), tz=timezone.utc)
            ) > timedelta(days=stale_ticket_days)
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 1))
                # Exponential backoff: wait longer on each retry
                wait_time = retry_after * (2**attempt)
                logging.warning(
                    f"Rate limited while fetching replies for ticket {ts}. "
                    f"Attempt {attempt + 1}/{max_retries}. Retrying after {wait_time} seconds."
                )
                await asyncio.sleep(wait_time)
                if attempt == max_retries - 1:
                    logging.error(f"Max retries exceeded for ticket {ts}")
                    return False
                continue
            elif e.response["error"] == "thread_not_found":
                logging.warning(
                    f"Thread not found for ticket {ts}. This might be a deleted thread."
                )
                maintainer_user = (
                    await User.objects()
                    .where(User.slack_id == env.slack_maintainer_id)
                    .first()
                )
                if maintainer_user:
                    await Ticket.update(
                        {
                            Ticket.status: TicketStatus.CLOSED,
                            Ticket.closed_at: datetime.now(),
                            Ticket.closed_by: maintainer_user.id,
                        }
                    ).where(Ticket.msg_ts == ts)
                else:
                    await Ticket.update(
                        {
                            Ticket.status: TicketStatus.CLOSED,
                            Ticket.closed_at: datetime.now(),
                        }
                    ).where(Ticket.msg_ts == ts)
                return False
            else:
                logging.error(
                    f"Error fetching replies for ticket {ts}: {e.response['error']}"
                )
                return False
    return False


STALE_INSTRUCTIONS = (
    "This support ticket has had no activity for a while. Should it be closed? "
    "Close it if the question was answered, the poster was redirected to another channel "
    "or resource (that counts as solved), a helper asked a follow-up and the poster never "
    "replied, the poster stopped replying or said thanks, or it is spam/test/nonsense/greeting. "
    "Keep it open ONLY if (a) nobody has replied to a real question yet, or (b) the poster's "
    "last message is a real question or complaint that no one answered or acted on."
)


async def jev_should_close(ticket: Ticket) -> bool | None:
    """Asks Jev whether a stale ticket should be closed. Without AI configured, every
    stale ticket closes (the old behaviour); on error, it stays open until the next run."""
    if not ai_client:
        return True
    try:
        replies = await env.slack_client.conversations_replies(
            channel=env.slack_help_channel,
            ts=ticket.msg_ts,
            include_all_metadata=True,
            limit=200,
        )
        thread = [
            {
                "role": "poster"
                if m.get("user") == ticket.opened_by.slack_id
                else "helper"  # macro replies (e.g. ?thread) are posted by the bot
                if (m.get("metadata") or {}).get("event_type") == "nephthys_macro_reply"
                else "bot"
                if m.get("bot_id")
                else "other",
                "text": m.get("text") or "",
            }
            for m in (replies["messages"] or [])[1:]
        ]
        if not any(m["role"] != "bot" for m in thread):
            return False  # nobody has replied yet, so it isn't solved
        response = await decisions(
            model=env.ai_stale_model,
            state={
                "question": {"title": ticket.title, "description": ticket.description},
                "replies": thread,
            },
            questions={
                "close": {
                    "type": "choice",
                    "instructions": STALE_INSTRUCTIONS,
                    "criteria": {
                        "close": "Close the ticket.",
                        "keep_open": "Leave it open, the poster still needs help.",
                    },
                }
            },
        )
        choice = response["answers"]["close"]["choice"]
        logging.info(f"Jev stale decision ticket={ticket.msg_ts} choice={choice}")
        return choice == "close"
    except Exception as e:
        logging.error(f"Jev stale decision failed ticket={ticket.msg_ts}: {e}")
        return None


async def close_stale_tickets():
    """
    Closes tickets that have been inactive for more than the configured number of days,
    based on the timestamp of the last message in the ticket's Slack thread.

    Configure via the STALE_TICKET_DAYS environment variable.
    This task is intended to be run periodically (e.g., hourly).
    """

    stale_ticket_days = env.stale_ticket_days
    if not stale_ticket_days:
        logging.warning("Skipping ticket auto-close (STALE_TICKET_DAYS not set)")
        return

    logging.info(f"Closing stale tickets, threshold_days={stale_ticket_days}")

    try:
        tickets = await Ticket.objects(Ticket.opened_by, Ticket.assigned_to).where(
            Ticket.status != TicketStatus.CLOSED
        )
        stale = 0

        # Process tickets in batches to avoid overwhelming the API
        batch_size = 10
        for i in range(0, len(tickets), batch_size):
            batch = tickets[i : i + batch_size]
            logging.info(
                f"Processing stale tickets batch={i // batch_size + 1} batches={(len(tickets) + batch_size - 1) // batch_size}"
            )

            for ticket in batch:
                await asyncio.sleep(1.2)  # Rate limiting delay

                if await get_is_stale(ticket.msg_ts, stale_ticket_days):
                    # Piccolo returns an empty `User` (slack_id=None) for unassigned tickets
                    assignee = (
                        ticket.assigned_to
                        if getattr(ticket.assigned_to, "slack_id", None)
                        else None
                    )
                    resolver_user = assignee or ticket.opened_by
                    if not resolver_user:
                        logging.warning(
                            f"Skipping stale ticket {ticket.msg_ts}: no assigned or opened user"
                        )
                        continue
                    should_close = await jev_should_close(ticket)
                    if should_close is None:
                        continue
                    if not should_close:
                        if assignee:
                            # The nudge is a new reply, so the ticket isn't stale again
                            # for another stale_ticket_days.
                            await env.slack_client.chat_postMessage(
                                channel=env.slack_help_channel,
                                thread_ts=ticket.msg_ts,
                                text=f":rac_nooo: <@{assignee.slack_id}> this ticket is still open",
                            )
                        continue
                    try:
                        await resolve(
                            ticket.msg_ts,
                            resolver_user.slack_id,
                            env.slack_client,
                            stale=True,
                        )
                    except Exception as e:
                        # One bad ticket (e.g. cant_delete_message) must not abort the run
                        logging.error(
                            f"Failed to close stale ticket {ticket.msg_ts}: {e}"
                        )
                        continue
                    stale += 1

            # Longer delay between batches
            if i + batch_size < len(tickets):
                await asyncio.sleep(5)

        logging.info(f"Closed stale tickets. count={stale}")
    except Exception as e:
        logging.error(f"Error closing stale tickets: {e}", exc_info=True)
