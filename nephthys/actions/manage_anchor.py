import asyncio
import logging
import re
from typing import Any
from typing import Dict

from slack_bolt.context.ack.async_ack import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.events.app_home_opened import open_app_home
from nephthys.utils.anchor import approve_change
from nephthys.utils.anchor import get_anchor
from nephthys.utils.anchor import is_helper
from nephthys.utils.anchor import notify_bts
from nephthys.utils.anchor import propose_change
from nephthys.utils.anchor import reject_change
from nephthys.utils.env import env
from nephthys.views.home import AppHomeView
from nephthys.views.modals.propose_anchor import get_propose_anchor_modal

# Slack broadcast / user-group mentions that would notify many people on every repost.
_BROADCAST_RE = re.compile(r"<!(channel|here|everyone)\b|<!subteam\^")


async def open_propose_anchor_modal(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    # One round-trip for both reads so we open the modal well within Slack's
    # ~3s trigger_id window.
    helper, anchor = await asyncio.gather(
        is_helper(user_id), get_anchor(env.slack_help_channel)
    )
    if not helper:
        return
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=get_propose_anchor_modal(anchor.text if anchor else None),
    )


async def propose_anchor_view_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        await ack()
        return
    text = body["view"]["state"]["values"]["anchor_text"]["anchor_text"]["value"]
    text = (text or "").strip()
    if not text:
        await ack(
            response_action="errors",
            errors={"anchor_text": "Please write the anchor message."},
        )
        return
    if _BROADCAST_RE.search(text):
        # The anchor is reposted every time it's buried, so a broadcast mention would
        # re-notify the whole channel repeatedly. Block it at proposal time.
        await ack(
            response_action="errors",
            errors={
                "anchor_text": "The anchor can't mention @channel, @here, @everyone or a user group."
            },
        )
        return
    await ack()
    current = await get_anchor(env.slack_help_channel)
    await propose_change(
        env.slack_help_channel, text, user_id, current.enabled if current else True
    )
    await notify_bts(
        f":pushpin: <@{user_id}> proposed a new help channel anchor message. Approve it in the App Home Anchor tab.\n>>> {text[:2500]}"
    )
    logging.info(f"Anchor change proposed by <@{user_id}> in {env.slack_help_channel}")
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def approve_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    result = await approve_change(
        env.slack_help_channel, user_id, int(body["actions"][0]["value"])
    )
    logging.info(
        f"Anchor approval by <@{user_id}> in {env.slack_help_channel}: {result}"
    )
    if result["status"] in ("recorded", "applied"):
        outcome = (
            "the change is now live"
            if result["status"] == "applied"
            else f"{result['count']}/{result['required']} approvals"
        )
        await notify_bts(
            f":white_check_mark: <@{user_id}> approved the pending anchor change: {outcome}."
        )
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def reject_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    if await reject_change(env.slack_help_channel, int(body["actions"][0]["value"])):
        await notify_bts(f":x: <@{user_id}> rejected the pending anchor change.")
    logging.info(f"Anchor change rejected by <@{user_id}> in {env.slack_help_channel}")
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def toggle_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    anchor = await get_anchor(env.slack_help_channel)
    if not anchor:
        return
    enabled = body["actions"][0]["value"] == "on"
    await propose_change(env.slack_help_channel, anchor.text, user_id, enabled)
    await notify_bts(
        f":pushpin: <@{user_id}> proposed turning the help channel anchor {'on' if enabled else 'off'}. Approve it in the App Home Anchor tab."
    )
    await open_app_home(AppHomeView.ANCHOR, client, user_id)
