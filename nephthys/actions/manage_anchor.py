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
from nephthys.utils.anchor import propose_change
from nephthys.utils.anchor import reject_change
from nephthys.utils.anchor import set_enabled
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
    if not await is_helper(user_id):
        return
    anchor = await get_anchor(env.slack_help_channel)
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
    await propose_change(env.slack_help_channel, text, user_id)
    logging.info(f"Anchor change proposed by <@{user_id}> in {env.slack_help_channel}")
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def approve_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    result = await approve_change(env.slack_help_channel, user_id)
    logging.info(
        f"Anchor approval by <@{user_id}> in {env.slack_help_channel}: {result}"
    )
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def reject_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    await reject_change(env.slack_help_channel)
    logging.info(f"Anchor change rejected by <@{user_id}> in {env.slack_help_channel}")
    await open_app_home(AppHomeView.ANCHOR, client, user_id)


async def toggle_anchor_callback(
    ack: AsyncAck, body: Dict[str, Any], client: AsyncWebClient
) -> None:
    await ack()
    user_id = body["user"]["id"]
    if not await is_helper(user_id):
        return
    enabled = body["actions"][0]["value"] == "on"
    await set_enabled(env.slack_help_channel, enabled)
    logging.info(
        f"Anchor turned {'on' if enabled else 'off'} by <@{user_id}> in {env.slack_help_channel}"
    )
    await open_app_home(AppHomeView.ANCHOR, client, user_id)
