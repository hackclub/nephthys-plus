from nephthys.database.tables import User
from nephthys.utils.anchor import get_anchor
from nephthys.utils.anchor import get_approvers
from nephthys.utils.anchor import get_proposal
from nephthys.utils.env import env
from nephthys.views.home import AppHomeView
from nephthys.views.home.components.header import get_header


def _preview(text: str, limit: int = 2000) -> str:
    return text[:limit] + ("..." if len(text) > limit else "")


async def get_anchor_view(user: User | None) -> dict:
    header = get_header(user, AppHomeView.ANCHOR)
    can_manage = bool(user and (user.helper or user.admin))
    channel = env.slack_help_channel

    anchor = await get_anchor(channel)
    proposal = await get_proposal(channel)
    required = env.anchor_approvals_required

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":pushpin: Channel Anchor",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rac_thumbs: the anchor is the message kept pinned at the bottom of <#{channel}>. "
                    f"changes need *{required}* helper{'s' if required != 1 else ''} to approve before they go live."
                    if can_manage
                    else f":rac_thumbs: note: you're not a helper, so you can only view the anchor for <#{channel}>"
                ),
            },
        },
        {"type": "divider"},
    ]

    if anchor and anchor.text:
        state = "on" if anchor.enabled else "off"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Current anchor* (`{state}`):\n{_preview(anchor.text)}",
                },
            }
        )
    else:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":rac_nooo: no anchor set yet"
                    + (", propose one below" if can_manage else ""),
                },
            }
        )

    blocks.append({"type": "divider"})

    if proposal:
        approvers = await get_approvers(proposal.id)
        approver_list = ", ".join(f"<@{a}>" for a in approvers)
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f":hourglass_flowing_sand: *Pending change* proposed by <@{proposal.proposer}>\n"
                        f"*{len(approvers)}/{required}* approvals: {approver_list}\n\n"
                        f"{_preview(proposal.text)}"
                    ),
                },
            }
        )
        if can_manage:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": ":white_check_mark: approve",
                            },
                            "action_id": "anchor-approve",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": ":x: reject"},
                            "action_id": "anchor-reject",
                            "style": "danger",
                            "confirm": {
                                "title": {
                                    "type": "plain_text",
                                    "text": "Reject change?",
                                },
                                "text": {
                                    "type": "plain_text",
                                    "text": "This discards the pending anchor change.",
                                },
                                "confirm": {"type": "plain_text", "text": "Reject"},
                                "deny": {"type": "plain_text", "text": "Cancel"},
                            },
                        },
                    ],
                }
            )
        blocks.append({"type": "divider"})

    if can_manage:
        elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": ":pencil2: propose a change"},
                "action_id": "anchor-propose",
                "style": "primary",
            }
        ]
        if anchor:
            toggle = "off" if anchor.enabled else "on"
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"turn anchor {toggle}"},
                    "action_id": "anchor-toggle",
                    "value": toggle,
                }
            )
        blocks.append({"type": "actions", "elements": elements})

    return {"type": "home", "blocks": [*header, *blocks]}
