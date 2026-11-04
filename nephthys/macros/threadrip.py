from nephthys.actions.resolve import resolve
from nephthys.database.enums import TicketStatus
from nephthys.macros.types import Macro
from nephthys.utils import prometheus
from nephthys.utils.env import env


class ThreadRip(Macro):
    name = "threadrip"
    can_run_on_closed = True

    async def run(self, ticket, helper, **kwargs):
        """
        Like ?thread, but nukes the whole thread: closes the ticket, then deletes
        the original ticket message and every reply.
        """
        parts = kwargs["text"].split(maxsplit=1)
        if len(parts) < 2:
            await env.slack_client.chat_postEphemeral(
                channel=env.slack_help_channel,
                thread_ts=ticket.msg_ts,
                user=helper.slack_id,
                text="`?threadrip` needs a reason, e.g. `?threadrip spam`.",
            )
            return

        if not await prometheus.can_delete_others():
            await env.slack_client.chat_postEphemeral(
                channel=env.slack_help_channel,
                thread_ts=ticket.msg_ts,
                user=helper.slack_id,
                text="`?threadrip` needs a Prometheus API key or a workspace admin user token, which this instance doesn't have.",
            )
            return

        if ticket.status != TicketStatus.CLOSED:
            await resolve(
                ts=ticket.msg_ts,
                resolver=helper.slack_id,
                client=env.slack_client,
                add_reaction=False,
                send_resolved_message=False,
            )

        await prometheus.delete_thread(
            thread_ts=ticket.msg_ts,
            channel=env.slack_help_channel,
            reason=f"?threadrip by <@{helper.slack_id}>: {parts[1].strip()}",
        )
