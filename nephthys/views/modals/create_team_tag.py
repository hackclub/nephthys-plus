def get_create_team_tag_modal():
    return {
        "type": "modal",
        "callback_id": "create_team_tag",
        "title": {
            "type": "plain_text",
            "text": ":rac_info: create a tag!",
            "emoji": True,
        },
        "blocks": [
            {
                "type": "input",
                "block_id": "tag_name",
                "label": {
                    "type": "plain_text",
                    "text": "giv name?",
                    "emoji": True,
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "tag_name",
                },
            },
            {
                "type": "input",
                "block_id": "tag_description",
                "label": {
                    "type": "plain_text",
                    "text": "description (comma-separated keywords for auto-tagging)",
                    "emoji": True,
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "tag_description",
                },
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "tag_always_tag",
                "label": {
                    "type": "plain_text",
                    "text": "always auto-tag when keywords match?",
                    "emoji": True,
                },
                "element": {
                    "type": "checkboxes",
                    "action_id": "tag_always_tag",
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": "yes, auto-tag tickets matching the description keywords",
                                "emoji": True,
                            },
                            "value": "true",
                        }
                    ],
                },
                "optional": True,
            },
        ],
        "submit": {
            "type": "plain_text",
            "text": ":rac_question: add tag?",
            "emoji": True,
        },
    }
