from nephthys.actions.resolve import resolve
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.utils.env import env
from nephthys.utils.slack_user import get_user_profile
from nephthys.utils.ticket_methods import reopen_blocks
from nephthys.utils.ticket_methods import reply_to_ticket


class Macro:
    name: str
    aliases: list[str] = []
    can_run_on_closed: bool = False
    post_as_helper: bool = False

    async def run(self, ticket: Ticket, helper: User, **kwargs) -> bool | None:
        """
        Run the macro with the given arguments. Return True if the macro already
        removed its own trigger message (so it shouldn't be deleted again).
        """
        raise NotImplementedError("Subclasses must implement this method.")

    async def helper_identity(self, helper: User) -> tuple[str | None, str | None]:
        if not self.post_as_helper:
            return None, None
        profile = await get_user_profile(helper.slack_id)
        return profile.display_name(), profile.profile_pic_512x()

    def helper_metadata(self, helper: User) -> dict | None:
        if not self.post_as_helper:
            return None
        return {
            "event_type": "nephthys_macro_reply",
            "event_payload": {"source_user_id": helper.slack_id},
        }

    def all_aliases(self) -> set[str]:
        """
        Get all names for this macro, including aliases.
        """
        return set([self.name] + self.aliases)


class ReplyMacro(Macro):
    """
    A type of simple macro that follows lookup, then reply, and possibly
    resolve.

    This type of macro:
    * Looks up the sender
    * Replies to the ticket with ``message``
    * Resolves the ticket (if ``resolve_ticket``)

    Macros that have complex logic should be based on ``Macro``.
    """

    message: str | None
    resolve_ticket: bool = True
    can_run_on_closed = False

    async def run(self, ticket: Ticket, helper: User, **kwargs) -> None:
        # Handle macros that may only be configured for certain events
        if not self.message:
            await env.slack_client.chat_postEphemeral(
                channel=env.slack_help_channel,
                thread_ts=ticket.msg_ts,
                user=helper.slack_id,
                text=f"Invalid macro: The `{self.name}` macro is not configured for this channel.",
            )
            return

        # Save API calls by only fetching user if used by message
        reply_text = self.message
        if "(user)" in self.message:
            # opened_by may be a prefetched User object or a raw FK int
            sender = ticket.opened_by
            if isinstance(sender, int):
                sender = await User.objects().where(User.id == sender).first()
            if not sender:
                return
            user = await get_user_profile(sender.slack_id)
            reply_text = self.message.replace("(user)", user.display_name())

        username, icon_url = await self.helper_identity(helper)

        await reply_to_ticket(
            text=reply_text,
            blocks=reopen_blocks(reply_text, ticket) if self.resolve_ticket else None,
            ticket=ticket,
            client=env.slack_client,
            username=username,
            icon_url=icon_url,
            metadata=self.helper_metadata(helper),
        )

        if self.resolve_ticket:
            await resolve(
                ts=ticket.msg_ts,
                resolver=helper.slack_id,
                client=env.slack_client,
                send_resolved_message=False,
            )
