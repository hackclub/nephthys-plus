from slack_sdk.web.async_client import AsyncWebClient

from nephthys.database.tables import CategoryTag
from nephthys.database.tables import TagsOnTickets
from nephthys.database.tables import TeamTag
from nephthys.database.tables import User
from nephthys.utils.env import env


async def backend_message_blocks(
    author_user_id: str,
    msg_ts: str,
    past_tickets: int,
    current_category_tag_id: int | None = None,
    reopened_by: User | None = None,
    ticket_id: int | None = None,
    current_team_tag_ids: list[int] | None = None,
) -> list[dict]:
    thread_url = f"https://hackclub.slack.com/archives/{env.slack_help_channel}/p{msg_ts.replace('.', '')}"
    if current_category_tag_id is not None:
        options = [
            {
                "text": {
                    "type": "plain_text",
                    "text": tag.name,
                },
                "value": f"{tag.id}",
            }
            for tag in await CategoryTag.objects()
        ]
        initial_option = [
            option
            for option in options
            if option["value"] == f"{current_category_tag_id}"
        ][0]
    else:
        initial_option = None
    category_tags_dropdown = {
        "type": "input",
        "label": {"type": "plain_text", "text": "Category tag", "emoji": True},
        "element": {
            "type": "external_select",
            "action_id": "category-tag-list",
            "placeholder": {
                "type": "plain_text",
                "text": "Which category tag fits?",
            },
            "min_query_length": 0,
        },
    }
    if initial_option:
        category_tags_dropdown["element"]["initial_option"] = initial_option

    team_tags_dropdown = {
        "type": "input",
        "label": {"type": "plain_text", "text": "Team tags", "emoji": True},
        "element": {
            "action_id": "team-tag-list",
            "type": "multi_external_select",
            "placeholder": {"type": "plain_text", "text": "Select tags"},
            "min_query_length": 0,
        },
    }
    if ticket_id is not None:
        team_tag_ids = (
            await TagsOnTickets.select(TagsOnTickets.tag)
            .where(TagsOnTickets.ticket == ticket_id)
            .output(as_list=True)
        )
        team_tags = (
            await TeamTag.objects().where(TeamTag.id.is_in(team_tag_ids))
            if team_tag_ids
            else []
        )
    elif current_team_tag_ids:
        team_tags = await TeamTag.objects().where(
            TeamTag.id.is_in(current_team_tag_ids)
        )
    else:
        team_tags = []
    if team_tags:
        team_tags_dropdown["element"]["initial_options"] = [
            {
                "text": {"type": "plain_text", "text": tag.name},
                "value": str(tag.id),
            }
            for tag in team_tags
        ]

    return [
        category_tags_dropdown,
        team_tags_dropdown,
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Reopened by <@{reopened_by.slack_id}>. Originally submitted by <@{author_user_id}>. <{thread_url}|View thread>."
                        if reopened_by
                        else f"Submitted by <@{author_user_id}>. They have {past_tickets} past tickets. <{thread_url}|View thread>."
                    ),
                }
            ],
        },
    ]


def backend_message_fallback_text(
    author_user_id: str,
    description: str,
    reopened_by: User | None = None,
) -> str:
    return (
        f"Reopened ticket from <@{author_user_id}>: {description}"
        if reopened_by
        else f"New question from <@{author_user_id}>: {description}"
    )


async def send_backend_message(
    author_user_id: str,
    msg_ts: str,
    description: str,
    past_tickets: int,
    client: AsyncWebClient,
    current_category_tag_id: int | None = None,
    reopened_by: User | None = None,
    ticket_id: int | None = None,
    current_team_tag_ids: list[int] | None = None,
    display_name: str | None = None,
    profile_pic: str | None = None,
):
    """Send a "backend" message to the tickets channel with ticket details."""

    return await client.chat_postMessage(
        channel=env.slack_ticket_channel,
        text=backend_message_fallback_text(author_user_id, description, reopened_by),
        blocks=await backend_message_blocks(
            author_user_id,
            msg_ts,
            past_tickets,
            current_category_tag_id,
            reopened_by,
            ticket_id=ticket_id,
            current_team_tag_ids=current_team_tag_ids,
        ),
        username=display_name,
        icon_url=profile_pic,
        metadata={
            "event_type": "nephthys_ticket_message",
            "event_payload": {"source_user_id": author_user_id},
        },
        unfurl_links=True,
        unfurl_media=True,
    )
