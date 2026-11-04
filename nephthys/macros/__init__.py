import logging
from typing import Any

from nephthys.database.enums import TicketStatus
from nephthys.database.tables import Macro as MacroTable
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.macros.deleteop import DeleteOP
from nephthys.macros.faq import FAQ
from nephthys.macros.forward import Forward
from nephthys.macros.fraud import Fraud
from nephthys.macros.hackatime import Hackatime
from nephthys.macros.hello_world import HelloWorld
from nephthys.macros.identity import Identity
from nephthys.macros.reopen import Reopen
from nephthys.macros.resolve import Resolve
from nephthys.macros.shipwrights import Shipwrights
from nephthys.macros.stale import Stale
from nephthys.macros.team_tag import TeamTag
from nephthys.macros.thread import Thread
from nephthys.macros.threadrip import ThreadRip
from nephthys.macros.trigger_daily_stats import DailyStats
from nephthys.macros.types import Macro
from nephthys.macros.types import ReplyMacro
from nephthys.utils import prometheus
from nephthys.utils.env import env

macro_list: list[type[Macro]] = [
    Resolve,
    HelloWorld,
    FAQ,
    Identity,
    Fraud,
    Thread,
    Forward,
    ThreadRip,
    DeleteOP,
    Reopen,
    DailyStats,
    Shipwrights,
    TeamTag,
    Hackatime,
    Stale,
]

macros = [macro() for macro in macro_list]


async def run_macro(
    name: str, ticket: Ticket, helper: User, macro_ts: str, text: str, **kwargs: Any
) -> bool:
    """
    Run the macro with the given name and arguments.
    """

    async def error_msg(msg: str):
        return await env.slack_client.chat_postEphemeral(
            channel=env.slack_help_channel,
            thread_ts=ticket.msg_ts,
            user=helper.slack_id,
            text=msg,
        )

    target_macro: Macro | None = None
    for macro in macros:
        if name in macro.all_aliases():
            target_macro = macro
            break

    if not target_macro:
        db_macro = (
            await MacroTable.objects()
            .where(
                (MacroTable.name == name.lower()) & (MacroTable.program == env.program)
            )
            .first()
        )
        if db_macro:
            target_macro = ReplyMacro()
            target_macro.name = db_macro.name
            target_macro.message = db_macro.message
            target_macro.resolve_ticket = db_macro.resolve_ticket
            target_macro.can_run_on_closed = db_macro.can_run_on_closed
            target_macro.post_as_helper = db_macro.post_as_helper

    if target_macro:
        if not target_macro.can_run_on_closed and ticket.status == TicketStatus.CLOSED:
            await error_msg(f"`?{name}` cannot be run on a closed ticket.")
            return False

        new_kwargs = kwargs.copy()
        new_kwargs["text"] = text
        await target_macro.run(ticket, helper, **new_kwargs)
        await prometheus.delete_message(
            ts=macro_ts,
            channel=env.slack_help_channel,
            reason=f"?{name} macro trigger",
            actor_slack_id=helper.slack_id,
        )
        return True

    await error_msg(f"`?{name}` is not a valid macro.")
    logging.info(
        f"Macro {name} not found from <@{helper.slack_id}>. ticket_id={ticket.id} helper_id={helper.id}"
    )
    return False
