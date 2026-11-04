from nephthys.macros.types import Macro
from nephthys.utils import prometheus
from nephthys.utils.env import env


class DeleteOP(Macro):
    name = "deleteop"
    can_run_on_closed = True

    async def run(self, ticket, helper, **kwargs):
        if not await prometheus.can_delete_others():
            await env.slack_client.chat_postEphemeral(
                channel=env.slack_help_channel,
                thread_ts=ticket.msg_ts,
                user=helper.slack_id,
                text="`?deleteop` needs a Prometheus API key or a workspace admin user token, which this instance doesn't have.",
            )
            return

        await prometheus.delete_message(
            ts=ticket.msg_ts,
            channel=env.slack_help_channel,
            reason=f"?deleteop by <@{helper.slack_id}>",
        )
