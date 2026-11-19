# Channel anchor: a message Nephthys keeps pinned at the bottom of a channel.
#
# Modeled on slack-extra's `/se anchor`, but changes to the anchor text go through a
# helper approval gate: a proposed change only goes live once `ANCHOR_APPROVALS_REQUIRED`
# distinct helpers (the proposer counts as one) have approved it. The help channel is the
# first thing many thousands of people see, so no single helper can change it alone.
#
# - Reposts are coalesced and rate limited per channel: a burst of messages gives one
#   trailing repost, not one each.
# - The anchor is posted, pinned and deleted with the bot token (the bot owns it): the
#   new copy is posted before the old one is removed, so the channel is never left
#   without an anchor and a failed post never leaves a duplicate.
# - Prometheus is used only to delete replies people post in the anchor's thread, which
#   the bot cannot delete itself (as slack-extra's `/se anchor` does).
import asyncio
import logging
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from slack_sdk.errors import SlackApiError

from nephthys.database.tables import Anchor
from nephthys.database.tables import AnchorApproval
from nephthys.database.tables import AnchorProposal
from nephthys.database.tables import User
from nephthys.utils.env import env
from nephthys.utils.prometheus import delete_message

MIN_REPOST_SECONDS = 60

# Message subtypes that actually bury the anchor and so warrant a repost. A message
# with no subtype always counts; everything else (joins, leaves, topic changes, …)
# does not. Mirrors message_creation.ALLOWED_SUBTYPES.
_REPOST_TRIGGER_SUBTYPES = ("file_share", "me_message", "thread_broadcast")

# Per-channel coalescing so concurrent triggers produce at most one trailing repost.
# These are in-memory, so correctness assumes a single bot process (as deployed today).
_channel_locks: dict[str, asyncio.Lock] = {}
_dirty_channels: set[str] = set()
# Serialises propose/approve/apply per channel so concurrent approvals can't double
# apply, and a new proposal can't race the UNIQUE(channel_id) constraint.
_proposal_locks: dict[str, asyncio.Lock] = {}
# Keep strong references to fire-and-forget repost tasks so they aren't garbage
# collected mid-run (per the asyncio.create_task docs).
_background_tasks: set[asyncio.Task] = set()


def _lock_for(channel: str) -> asyncio.Lock:
    lock = _channel_locks.get(channel)
    if lock is None:
        lock = _channel_locks[channel] = asyncio.Lock()
    return lock


def _proposal_lock_for(channel: str) -> asyncio.Lock:
    lock = _proposal_locks.get(channel)
    if lock is None:
        lock = _proposal_locks[channel] = asyncio.Lock()
    return lock


async def is_helper(slack_id: str) -> bool:
    user = await User.objects().where(User.slack_id == slack_id).first()
    return bool(user and (user.helper or user.admin))


async def get_anchor(channel: str) -> Anchor | None:
    return await Anchor.objects().where(Anchor.channel_id == channel).first()


def _is_expired(proposal: AnchorProposal) -> bool:
    days = env.anchor_proposal_expiry_days
    if days <= 0:
        return False
    return proposal.created_at < datetime.now(timezone.utc) - timedelta(days=days)


async def get_proposal(channel: str) -> AnchorProposal | None:
    proposal = (
        await AnchorProposal.objects()
        .where(AnchorProposal.channel_id == channel)
        .first()
    )
    if proposal and _is_expired(proposal):
        # Drop a proposal that sat unapproved past the expiry window, so it can't
        # be approved later by helpers who've lost the original context.
        await AnchorProposal.delete().where(AnchorProposal.id == proposal.id)
        return None
    return proposal


async def get_approvers(proposal_id: int) -> list[str]:
    rows = await AnchorApproval.select(AnchorApproval.approver).where(
        AnchorApproval.proposal == proposal_id
    )
    return [row["approver"] for row in rows]


# --- reposting --------------------------------------------------------------


_CLEANUP_OK = ("no_pin", "not_pinned", "message_not_found", "cant_delete_message")


async def _remove_old_anchor(channel: str, ts: str) -> None:
    """Unpin and delete the previous anchor. The bot posted it, so the bot deletes it."""
    try:
        await env.slack_client.pins_remove(channel=channel, timestamp=ts)
    except SlackApiError as e:
        error = e.response.get("error")
        if error not in _CLEANUP_OK:
            logging.warning(f"Failed to unpin old anchor ts={ts} in {channel}: {error}")
    try:
        await env.slack_client.chat_delete(channel=channel, ts=ts)
    except SlackApiError as e:
        error = e.response.get("error")
        if error not in _CLEANUP_OK:
            logging.warning(
                f"Failed to delete old anchor ts={ts} in {channel}: {error}"
            )


async def _repost(channel: str) -> None:
    anchor = await get_anchor(channel)
    if not anchor or not anchor.enabled or not anchor.text:
        return

    old_ts = anchor.message_ts
    # Record the attempt time up front so repeated post failures still respect the
    # rate limit (request_repost reads posted_at), instead of retrying on every message.
    await Anchor.update({Anchor.posted_at: datetime.now(timezone.utc)}).where(
        Anchor.channel_id == channel
    )

    # Post the new copy before removing the old one, so the channel is never left
    # without an anchor and a failed post never produces a duplicate (cf. nps.py).
    try:
        msg = await env.slack_client.chat_postMessage(
            channel=channel,
            text=anchor.text,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as e:
        logging.error(f"Failed to post anchor in {channel}: {e.response.get('error')}")
        return

    await Anchor.update({Anchor.message_ts: msg["ts"]}).where(
        Anchor.channel_id == channel
    )

    try:
        await env.slack_client.pins_add(channel=channel, timestamp=msg["ts"])
    except SlackApiError as e:
        logging.warning(f"Failed to pin anchor in {channel}: {e.response.get('error')}")

    if old_ts:
        await _remove_old_anchor(channel, old_ts)


async def request_repost(channel: str) -> None:
    """Repost the anchor, coalescing bursts and rate limiting to one per minute."""
    _dirty_channels.add(channel)
    async with _lock_for(channel):
        if channel not in _dirty_channels:
            return  # a concurrent repost already covered us
        cleared = False
        try:
            anchor = await get_anchor(channel)
            if not anchor:
                return
            posted_at = anchor.posted_at.timestamp() if anchor.posted_at else 0
            wait = MIN_REPOST_SECONDS - (time.time() - posted_at)
            if wait > 0:
                await asyncio.sleep(wait)
            # Clear dirty before posting so triggers during the post get a trailing
            # repost rather than being swallowed.
            _dirty_channels.discard(channel)
            cleared = True
            await _repost(channel)
        except Exception:
            logging.exception(f"Anchor repost failed in {channel}")
        finally:
            if not cleared:
                _dirty_channels.discard(channel)


def trigger_repost(channel: str) -> None:
    """Fire-and-forget repost; safe to call from a Slack event handler."""
    task = asyncio.create_task(request_repost(channel))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def handle_channel_message(event: dict) -> None:
    """Repost the anchor when a new message buries it in the help channel."""
    channel = event.get("channel")
    if not channel:
        return
    anchor = await get_anchor(channel)
    if not anchor or not anchor.enabled:
        return
    if event.get("ts") == anchor.message_ts:
        return
    if event.get("bot_id") or event.get("subtype") in (
        "bot_message",
        "message_changed",
        "message_deleted",
    ):
        # Bot posts (including deletion notices) must not trigger reposts, or they loop.
        return

    thread_ts = event.get("thread_ts")
    if thread_ts and thread_ts == anchor.message_ts and event.get("ts") != thread_ts:
        # People shouldn't reply in the anchor's thread; the bot can't delete their
        # messages, so Prometheus removes them (the anchor isn't a discussion thread).
        try:
            await delete_message(
                event["ts"], channel, reason="Reply in the channel anchor thread"
            )
        except Exception:
            logging.exception(f"Failed to delete anchor-thread reply in {channel}")
        return
    if thread_ts and event.get("subtype") != "thread_broadcast":
        # Other threaded replies don't bury the anchor in the channel timeline; ignore them.
        return
    subtype = event.get("subtype")
    if subtype is not None and subtype not in _REPOST_TRIGGER_SUBTYPES:
        # Only real posts bury the anchor. System messages like channel joins/leaves
        # don't, and Slack stops rendering join lines in large channels anyway.
        return
    trigger_repost(channel)


async def ensure_latest(channel: str) -> None:
    """Repost the anchor if it isn't the channel's latest message (recovers downtime)."""
    anchor = await get_anchor(channel)
    if not anchor or not anchor.enabled:
        return
    try:
        history = await env.slack_client.conversations_history(channel=channel, limit=1)
    except SlackApiError as e:
        logging.warning(
            f"Anchor startup check failed in {channel}: {e.response.get('error')}"
        )
        return
    messages = history.get("messages") or []
    latest_ts = messages[0].get("ts") if messages else None
    if anchor.message_ts and latest_ts == anchor.message_ts:
        return
    await request_repost(channel)


# --- proposals and approvals ------------------------------------------------


async def _apply_proposal(channel: str, proposal: AnchorProposal) -> None:
    # Re-check the proposal still exists: it may have been superseded or rejected
    # between the approval that triggered this and now.
    still = (
        await AnchorProposal.objects().where(AnchorProposal.id == proposal.id).first()
    )
    if not still:
        return
    existing = await get_anchor(channel)
    old_ts = existing.message_ts if existing else None
    if existing:
        await Anchor.update(
            {Anchor.text: proposal.text, Anchor.enabled: proposal.enabled}
        ).where(Anchor.channel_id == channel)
    else:
        await Anchor(
            channel_id=channel, text=proposal.text, enabled=proposal.enabled
        ).save()
    # Deleting the proposal cascades to its approvals.
    await AnchorProposal.delete().where(AnchorProposal.id == proposal.id)
    if proposal.enabled:
        trigger_repost(channel)
    elif old_ts:
        # Turning the anchor off removes the pinned message too, not just future reposts.
        await _remove_old_anchor(channel, old_ts)
        await Anchor.update({Anchor.message_ts: None}).where(
            Anchor.channel_id == channel
        )


async def propose_change(
    channel: str, text: str, proposer: str, enabled: bool = True
) -> AnchorProposal:
    """Replace any pending proposal with a new one, counting the proposer as approval #1."""
    async with _proposal_lock_for(channel):
        await AnchorProposal.delete().where(AnchorProposal.channel_id == channel)
        proposal = AnchorProposal(
            channel_id=channel, text=text, proposer=proposer, enabled=enabled
        )
        await proposal.save()
        await AnchorApproval(proposal=proposal.id, approver=proposer).save()
        if env.anchor_approvals_required <= 1:
            await _apply_proposal(channel, proposal)
        return proposal


async def approve_change(channel: str, approver: str, proposal_id: int) -> dict:
    """Record an approval for a specific proposal. Applies it once enough helpers approve.

    Returns {"status": "applied"|"recorded"|"already"|"none", "count", "required"}.
    """
    async with _proposal_lock_for(channel):
        proposal = await get_proposal(channel)
        required = env.anchor_approvals_required
        if not proposal or proposal.id != proposal_id:
            return {"status": "none", "count": 0, "required": required}

        approvers = await get_approvers(proposal.id)
        if approver in approvers:
            return {"status": "already", "count": len(approvers), "required": required}
        await AnchorApproval(proposal=proposal.id, approver=approver).save()
        approvers.append(approver)

        if len(approvers) >= required:
            await _apply_proposal(channel, proposal)
            return {"status": "applied", "count": len(approvers), "required": required}
        return {"status": "recorded", "count": len(approvers), "required": required}


async def reject_change(channel: str, proposal_id: int) -> bool:
    """Discard the pending proposal. Returns True if there was one."""
    async with _proposal_lock_for(channel):
        proposal = await get_proposal(channel)
        if not proposal or proposal.id != proposal_id:
            return False
        await AnchorProposal.delete().where(AnchorProposal.id == proposal.id)
        return True


async def notify_bts(text: str) -> None:
    if not env.slack_bts_channel or env.slack_bts_channel == "unset":
        return
    try:
        await env.slack_client.chat_postMessage(
            channel=env.slack_bts_channel, text=text, unfurl_links=False
        )
    except SlackApiError as e:
        logging.warning(f"Failed to notify BTS about anchor: {e.response.get('error')}")
