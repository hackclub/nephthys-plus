def get_propose_anchor_modal(current_text: str | None = None) -> dict:
    return {
        "type": "modal",
        "callback_id": "anchor_propose_form",
        "title": {"type": "plain_text", "text": ":pushpin: Anchor", "emoji": True},
        "submit": {"type": "plain_text", "text": "Propose"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Write the new anchor message. It goes live once enough helpers approve it. You count as the first approval.",
                },
            },
            {
                "type": "input",
                "block_id": "anchor_text",
                "label": {"type": "plain_text", "text": "Anchor message (markdown)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "anchor_text",
                    "multiline": True,
                    "initial_value": current_text or "",
                },
            },
        ],
    }
