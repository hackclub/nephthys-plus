from nephthys.transcripts.transcript import Transcript


class Phantom(Transcript):
    """Transcript for Phantom"""

    program_name: str = "Phantom"
    program_owner: str = "U085KKYFA6Q"  # @devansh

    help_channel: str = "C0B3NSQCPQ9"
    team_channel: str = "C0C2Y8G6T5K"

    faq_link: str = "https://hackclub.enterprise.slack.com/docs/T0266FRGM/F0C2L96DP0B"
    faq_canvas_id: str | None = "F0C2L96DP0B"

    first_ticket_create: str = f"""
A passing soul should be along to help you soon. In the meantime, I suggest you read the <{faq_link}|FAQ> to see if your question has already been answered. Once your question is answered, hit the button below to mark it as resolved.
"""
    ticket_create: str = first_ticket_create
