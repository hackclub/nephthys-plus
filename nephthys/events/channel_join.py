from slack_bolt.context.ack.async_ack import AsyncAck
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.tasks.update_helpers import update_helpers
from nephthys.utils import helper_oauth
from nephthys.utils.env import env


async def channel_join(ack: AsyncAck, event: dict, client: AsyncWebClient):
    await ack()
    channel_id = event["channel"]

    if channel_id in [env.slack_bts_channel, env.slack_ticket_channel]:
        await update_helpers()
        user_id = event["user"]
        if channel_id == env.slack_bts_channel and await helper_oauth.needs_connect(
            user_id
        ):
            await client.chat_postMessage(
                channel=user_id, text=helper_oauth.connect_text(user_id)
            )
    else:
        return
