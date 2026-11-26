from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class Transcript(BaseModel):
    """Class to hold all the transcript messages and links used in the bot."""

    class Config:
        """Configuration for the Pydantic model."""

        extra = "forbid"

    program_name: str = Field(
        default="Summer of Making", description="Name of the program"
    )
    program_owner: str = Field(
        default="U054VC2KM9P",
        description="Slack ID of the support manager",
    )
    help_channel: str = Field(
        default="",
        description="Slack channel ID for help requests",
    )
    ticket_channel: str = Field(
        default="",
        description="Slack channel ID for ticket creation",
    )
    team_channel: str = Field(
        default="",
        description="Slack channel ID for team discussions and stats",
    )
    ticket_reopen: str = Field(
        default="",
        description="Message when ticket is reopened",
    )

    @property
    def program_snake_case(self) -> str:
        """Snake case version of the program name."""
        return self.program_name.lower().replace(" ", "_")

    faq_link: str = Field(
        default="https://hackclub.slack.com/docs/T0266FRGM/F093F8D7EE9",
        description="FAQ link URL",
    )

    faq_canvas_id: str | None = Field(
        default=None,
        description="File ID of the FAQ canvas. When set, the bot reads the canvas and uses AI to link the exact FAQ question that answers a ticket",
    )

    faq_suggestion: str = Field(
        default=":rac_info: this bit of the faq might answer your question: <{url}|*{question}*>",
        description="Sent as a reply in the thread when the AI finds a matching FAQ entry",
    )

    faq_events_question: str | None = Field(
        default=None,
        description="The FAQ canvas question whose answer lists each event followed by its help channel. When set, the AI can tell people which event's help channel to ask in. Leave unset for programs without such a list",
    )

    slack_id_auto_reply: str = Field(
        default="hey, I think you're asking what your slack id is, it's {user_id} but in the future please just run /id (not in a thread). cheers!",
        description="Sent as a reply in the thread when a new question asks how to find a Slack ID. {user_id} is replaced with the poster's Slack ID. Leave empty to turn it off",
    )

    event_channel_suggestion: str = Field(
        default="hey, is this {program}? if so then ask in {channel}",
        description="Sent as a reply when the AI thinks the question is about a specific event. {program} is the event's name and {channel} is its help channel",
    )

    identity_help_channel: str = Field(
        default="C092833JXKK", description="Identity help channel ID"
    )

    first_ticket_create: str = Field(
        default="", description="Message for first-time ticket creators"
    )

    ticket_create: str = Field(default="", description="Message for ticket creation")

    wait_time_estimate: str = Field(
        default="_typical wait right now: about {wait}_",
        description="Small line under the welcome message. {wait} is replaced with the average time to a first reply (from anyone but the poster) over the last 7 days, without the fastest and slowest 7%. Leave empty to turn it off",
    )

    resolve_ticket_button: str = Field(
        default="Mark as resolved",
        description="Text for the green resolve-ticket button",
    )

    ticket_resolve: str = Field(
        default="", description="Message when ticket is resolved"
    )

    ticket_resolve_stale: str = Field(
        default="",
        description="Message when ticket is resolved due to being stale",
    )

    thread_broadcast_delete: str = Field(
        default="hey! please keep your messages *all in one thread* to make it easier to read! i've gone ahead and removed that message from the channel for ya :D",
    )

    ticket_feedback_text: str = Field(default="Feedback really helps us! Thanks <3")

    ## MACROS ##

    faq_macro: str = Field(
        default="", description="Message to be sent when the FAQ macro is used"
    )

    fraud_macro: str = Field(
        default="Hiya (user)! Would you mind directing any fraud related queries to <@U091HC53CE8>? :rac_cute:\n\nIt'll keep your case confidential and make it easier for the fraud team to keep track of!",
        description="Message to be sent when the fraud macro is used",
    )

    shipwrights_macro: str = Field(
        default="Hey, (user)!\nPlease ask questions about project shipping or certifications in <#C099P9FQQ91>.\n\nThe Shipwrights Team will help with your question!",
        description="Message to be sent when the shipwrights macro is used",
    )

    identity_macro: str = Field(
        default="", description="Message to be sent when the identity macro is used"
    )

    hackatime_macro: str = Field(
        default="Hi (user), could you ask that question in <#C0AFG0XGGMP>? :rac_cute:\n\nYou'll get better help for this Hackatime-specific question there!\n\n_I've marked this thread as resolved_",
        description="Message to be sent when the Hackatime macro is used",
    )

    stale_tickets_macro: str = Field(
        default="Hey, (user)! It seems like this ticket has been inactive for some days so I'll be closing it.\nIf your question wasn't answered, please feel free to make a new one. Thanks!",
        description="Message for closing stale tickets",
    )

    not_allowed_channel: str = Field(
        default="", description="Message for unauthorized channel access"
    )

    @model_validator(mode="after")
    def set_default_messages(self):
        """Set default values for messages that reference other fields"""
        if not self.first_ticket_create:
            self.first_ticket_create = f"""oh, hey (user) it looks like this is your first time here, welcome! someone should be along to help you soon but in the mean time i suggest you read the faq <{self.faq_link}|here>, it answers a lot of common questions.
if your question has been answered, please hit the button below to mark it as resolved
    """

        if not self.ticket_create:
            self.ticket_create = f"""someone should be along to help you soon but in the mean time i suggest you read the faq <{self.faq_link}|here> to make sure your question hasn't already been answered. if it has been, please hit the button below to mark it as resolved :D
    """

        if not self.ticket_resolve:
            self.ticket_resolve = f"""oh, oh! it looks like this post has been marked as resolved by <@{{user_id}}>! if you have any more questions, please make a new post in <#{self.help_channel}> and someone'll be happy to help you out! not me though, i'm just a silly racoon ^-^
    """

        if not self.ticket_resolve_stale:
            self.ticket_resolve_stale = f""":rac_nooo: it looks like this post is a bit old! if you still need help, please make a new post in <#{self.help_channel}> and someone'll be happy to help you out! ^~^
        """

        if not self.faq_macro:
            self.faq_macro = f"hey, (user)! this question is answered in the faq i sent earlier, please make sure to check it out! :rac_cute:\n\n<{self.faq_link}|here it is again>"

        if not self.identity_macro:
            self.identity_macro = f"hey, (user)! please could you ask questions about identity verification in <#{self.identity_help_channel}>? :rac_cute:\n\nit helps the verification team keep track of questions easier!"

        if not self.not_allowed_channel:
            self.not_allowed_channel = f"heya, it looks like you're not supposed to be in that channel, pls talk to <@{self.program_owner}> if that's wrong"

        if not self.ticket_reopen:
            self.ticket_reopen = "hey hey! it looks like <@{helper_slack_id}> has reopened this post! someone'll be with you shortly, ty!"

        return self
