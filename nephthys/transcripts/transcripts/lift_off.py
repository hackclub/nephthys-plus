from nephthys.transcripts.transcript import Transcript


class LiftOff(Transcript):
    """Transcript for Lift Off"""

    program_name: str = "lift-off.py"
    program_owner: str = "U0A9K5RT3HS"

    help_channel: str = "C0CDP2YQX7F"  # help
    ticket_channel: str = "C0CDD5Q5Q0P"  # help-ticket
    team_channel: str = "C0CDUANHDSN"  # help-channel-bts

    faq_link: str = "https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0CEP0DCRHN"
    faq_canvas_id: str | None = "F0CEP0DCRHN"
    faq_events_question: str | None = "How does it work?"

    first_ticket_create: str = f"""
hi (user)! seems like it's your first time, welcome to the help channel! someone will be here soon to help answer your question! for now, feel free to look at the <{faq_link}|faq>, it answers some common questions and gives basic information. 
if your question has been answered, please hit the button below to mark it as resolved ^-^
"""
    ticket_create: str = f"someone will be here soon to help answer your question! for now, feel free to look at the <{faq_link}|faq>, it answers some common questions and gives basic information. if your question has been answered, please hit the button below to mark it as resolved ^-^"
    resolve_ticket_button: str = "i get it now"
    ticket_resolve: str = "This thread has been closed by <@{user_id}> :yayayayayay:  If your question was still not answered, you can either reopen this thread or start a new ticket! :plane-flapping:"

    not_allowed_channel: str = f"heyo! doesn't seem like you're supposed to be in that channel, please reach out to <@{program_owner}> if that's wrong!"
