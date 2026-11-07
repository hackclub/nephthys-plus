import os
import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

for key, value in {
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_USER_TOKEN": "xoxp-test",
    "SLACK_SIGNING_SECRET": "test",
    "SLACK_HELP_CHANNEL": "C-help",
    "SLACK_TICKET_CHANNEL": "C-tickets",
    "SLACK_BTS_CHANNEL": "C-bts",
    "SLACK_MAINTAINER_ID": "U-maintainer",
    "PROGRAM": "help",
}.items():
    os.environ.setdefault(key, value)

from nephthys.events import message_creation
from nephthys.utils import slack
from nephthys.utils.env import parse_user_ids


class ParseUserIdsTests(unittest.TestCase):
    def test_empty_or_missing_value(self):
        self.assertEqual(parse_user_ids(None), frozenset())
        self.assertEqual(parse_user_ids(""), frozenset())

    def test_multiple_ids_and_whitespace(self):
        self.assertEqual(
            parse_user_ids(" U12345678, U87654321 ,, "),
            frozenset({"U12345678", "U87654321"}),
        )

    def test_environment_value_is_supported(self):
        with patch.dict(os.environ, {"IGNORED_USERS": "U12345678, U87654321"}):
            self.assertEqual(
                parse_user_ids(os.environ["IGNORED_USERS"]),
                frozenset({"U12345678", "U87654321"}),
            )

    def test_missing_user_id_is_safe(self):
        self.assertIsNone(message_creation.get_message_author_id({}))


class MessageFilteringTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ignored_users = patch.object(
            message_creation.env,
            "ignored_users",
            frozenset({"U-ignored"}),
        )
        self.ignored_users.start()
        self.addCleanup(self.ignored_users.stop)

    async def test_ignored_user_is_returned_before_database_lookup(self):
        with (
            patch.object(message_creation.Ticket, "objects") as ticket_objects,
            patch.object(
                message_creation, "handle_new_question", new_callable=AsyncMock
            ),
        ):
            await message_creation.on_message(
                {"user": "U-ignored", "channel": "C-help", "ts": "1"},
                MagicMock(),
            )
        ticket_objects.assert_not_called()

    async def test_ignored_thread_reply_is_returned_before_database_lookup(self):
        with patch.object(message_creation.User, "objects") as user_objects:
            await message_creation.on_message(
                {
                    "user": "U-ignored",
                    "channel": "C-help",
                    "ts": "2",
                    "thread_ts": "1",
                },
                MagicMock(),
            )
        user_objects.assert_not_called()

    async def test_forwarded_ignored_original_is_filtered(self):
        with patch.object(message_creation.Ticket, "objects") as ticket_objects:
            await message_creation.on_message(
                {
                    "user": "U-forwarder",
                    "channel": "C-help",
                    "ts": "3",
                    "metadata": {
                        "event_type": "nephthys_plus_forward",
                        "event_payload": {
                            "ticket": True,
                            "source_user_id": "U-ignored",
                        },
                    },
                },
                MagicMock(),
            )
        ticket_objects.assert_not_called()

    async def test_forwarded_nonignored_original_is_not_filtered(self):
        ticket_query = MagicMock()
        ticket_query.where.return_value = ticket_query
        ticket_query.first = AsyncMock(return_value=None)
        user_query = MagicMock()
        user_query.where.return_value = user_query
        user_query.first = AsyncMock(return_value=None)
        forwarded_events = []

        async def capture_event(event, client, db_user):
            forwarded_events.append(event)

        with (
            patch.object(
                message_creation.Ticket,
                "objects",
                return_value=ticket_query,
            ),
            patch.object(
                message_creation.User,
                "objects",
                return_value=user_query,
            ),
            patch.object(
                message_creation,
                "handle_new_question",
                side_effect=capture_event,
            ),
        ):
            await message_creation.on_message(
                {
                    "user": "U-forwarder",
                    "channel": "C-help",
                    "ts": "4",
                    "metadata": {
                        "event_type": "nephthys_plus_forward",
                        "event_payload": {
                            "ticket": True,
                            "source_user_id": "U-original",
                        },
                    },
                },
                MagicMock(),
            )
        self.assertEqual(
            forwarded_events[0]["user"],
            "U-original",
        )

    async def test_ignored_user_cannot_trigger_ai_action(self):
        ack = AsyncMock()
        handler = slack.handle_ask_ai_button
        assert handler is not None
        with patch.object(slack, "ask_ai", new_callable=AsyncMock) as ask_ai:
            await handler(
                ack,
                {"user": {"id": "U-ignored"}},
                MagicMock(),
            )
        ack.assert_awaited_once()
        ask_ai.assert_not_awaited()

    async def test_empty_ignore_list_preserves_normal_message_processing(self):
        with (
            patch.object(message_creation.env, "ignored_users", frozenset()),
            patch.object(message_creation, "maybe_promote"),
            patch.object(message_creation.User, "objects") as user_objects,
            patch.object(
                message_creation,
                "handle_new_question",
                new_callable=AsyncMock,
            ) as handle_new_question,
        ):
            user_objects.return_value.where.return_value.first = AsyncMock(
                return_value=None
            )
            await message_creation.on_message(
                {"user": "U-normal", "channel": "C-help", "ts": "5"},
                MagicMock(),
            )
        handle_new_question.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
