from nephthys.transcripts.transcript import Transcript


class Orchard(Transcript):
    """Transcript for Orchard Support"""

    program_name: str = "Orchard"
    program_owner: str = "U07UBCSSQH3"

    help_channel: str = "C0C0J6XCA8Y"  # orchard-support
    ticket_channel: str = "C0BC78VT9KM"
    team_channel: str = "C0BC78VT9KM"

    first_ticket_create: str = """Heya (user)! Welcome to the Orchard support channel!
Seb will help you soon, so please wait for a bit.
If your question has been answered, please hit the button below to mark it as resolved!
    """

    ticket_create: str = """Hi (user), welcome back to the Orchard support channel!
Seb will help you soon, so please wait for a bit.
    """

    resolve_ticket_button: str = "Mark As Resolved"

    ticket_resolve: str = f"<@{{user_id}}> has marked this as resolved. If you think this was a mistake, you may reopen this ticket. More questions? Feel free to send another message in <#{help_channel}> and we'll be there to help too!"

    not_allowed_channel: str = f"Heya, it looks like you're not supposed to be in that channel, pls talk to <@{program_owner}> If that's wrong."
