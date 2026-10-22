from nephthys.transcripts.transcript import Transcript


class Twisted(Transcript):
    """Transcript for Twisted YSWS."""

    program_name: str = "Twisted"
    program_owner: str = "U0A5NKH93BJ"  # @aoishik

    help_channel: str = "C0BQM80CQQ6"  # #Twisted-help
    ticket_channel: str = "C0BKG9RBZRR"
    team_channel: str = "C0BKH9PQLPP"

    faq_link: str = "https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0BQVBNNVJR"
    faq_canvas_id: str | None = "F0BQVBNNVJR"
    faq_events_question: str | None = None

    first_ticket_create: str = """
Heya (user)! Welcome to the Twisted help channel! Someone from our team will be here to help you out soon.
If you haven't already, have a read through <https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0BKPDUDTGV|*the FAQ*> – it will likely contain the answer you're looking for!
If your question has been answered, please hit the button below to mark it as resolved!
    """

    ticket_create: str = """
Hi (user), welcome back to the Twisted help channel! Someone should be along to help you soon.
As a reminder, you can take a look at <https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0BKPDUDTGV|*the FAQ*> while you wait – it might contain the answer to your question! :D
"""

    resolve_ticket_button: str = "Mark As Resolved"

    ticket_resolve: str = (
        "<@{user_id}> has marked this as resolved. "
        "If you think this was a mistake, you may reopen this ticket. "
        "More questions? Feel free to send another message in "
        "<#C0BQM80CQQ6> and we'll be there to help too!"
    )

    not_allowed_channel: str = (
        "Heya, it looks like you're not supposed to be in that channel, "
        "pls talk to <@U0A5NKH93BJ> If that's wrong."
    )

    faq_macro: str = """
Hi (user), this question is already answered in our FAQ!

Here's the link again: <https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0BKPDUDTGV|*Twisted FAQ*>.

_I've marked this question as resolved, so please start a new thread if you need more help_
"""
