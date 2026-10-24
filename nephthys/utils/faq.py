import logging
import re
from html.parser import HTMLParser
from typing import NamedTuple

from httpx import HTTPStatusError
from pydantic import BaseModel
from slack_sdk.web.async_client import AsyncWebClient

from nephthys.utils.ai import ai_client
from nephthys.utils.ai import ChoiceQuestion
from nephthys.utils.ai import decisions
from nephthys.utils.ai import DecisionsResponse
from nephthys.utils.ai import StructuredGuidance
from nephthys.utils.env import env

NO_MATCH = "none"
# "Event name #C123" on one line, or just "#C123" on the line after the name
CHANNEL_LINE = re.compile(r"^(?P<name>.*?)\s*#(?P<id>C[A-Z0-9]+)\s*$")


class FaqEntry(BaseModel):
    """A single question in the FAQ canvas."""

    section_id: str
    question: str
    answer: str


class EventChannel(NamedTuple):
    """An event and the channel to ask about it in."""

    name: str
    channel_id: str


class FaqMatch(NamedTuple):
    """What the AI picked for a message: an FAQ entry, or one event's help
    channel, or neither. At most one of the two is set."""

    entry: FaqEntry | None = None
    event: EventChannel | None = None


# Last successfully fetched FAQ, kept if a later refresh fails
faq_entries: list[FaqEntry] = []
# Only send a heartbeat for the first of several failures in a row
_last_refresh_failed = False
_events_entry_missing = False
MIN_EVENTS = 3


_EMOJI = re.compile(r":[a-z0-9_+\-]+:")
_HEADING_TAGS = {"h1", "h2", "h3"}
_BLOCK_TAGS = {"p", "td", "th"}


def _clean(text: str) -> str:
    """Collapse whitespace and drop :emoji: codes."""
    return " ".join(_EMOJI.sub("", text).split())


class _CanvasFaqParser(HTMLParser):
    """Pulls questions and answers out of a canvas's HTML.

    Two layouts are understood, and can be mixed in one canvas:

    - Bullets: each top-level bullet is a question, and the bullets nested
      under it are the answer:
      <ul><li id="...">Question</li><ul><li>Answer</li></ul></ul>
    - Sections: a heading is the question, and the text under it (paragraphs,
      table cells, plain bullets) up to the next heading is the answer. Only
      used for a section that has no bullet questions of its own.
    """

    def __init__(self):
        super().__init__()
        self.entries: list[FaqEntry] = []
        self.ul_depth = 0
        self.li: dict | None = None
        self.question: dict | None = None
        # Section layout
        self.heading: dict | None = None
        self.heading_text: list[str] | None = None
        self.heading_id: str | None = None
        self.block: list[str] | None = None
        self.lines: list[str] = []
        self.section_start = 0

    def handle_starttag(self, tag, attrs):
        if tag in _HEADING_TAGS:
            self._finish_section()
            self.heading_text = []
            self.heading_id = dict(attrs).get("id")
        elif tag == "ul":
            self.ul_depth += 1
        elif tag == "li":
            self.li = {"id": dict(attrs).get("id"), "text": []}
        elif tag in _BLOCK_TAGS and self.block is None and not self.li:
            self.block = []

    def handle_endtag(self, tag):
        if tag in _HEADING_TAGS and self.heading_text is not None:
            text = _clean("".join(self.heading_text))
            self.heading = {"id": self.heading_id, "text": text} if text else None
            self.heading_text = None
        elif tag in _BLOCK_TAGS and self.block is not None:
            text = _clean("".join(self.block))
            if text:
                self.lines.append(text)
            self.block = None
        elif tag == "ul":
            self.ul_depth -= 1
            if self.ul_depth == 0:
                self._finish_question()
        elif tag == "li" and self.li:
            text = " ".join("".join(self.li["text"]).split())
            if self.ul_depth == 1:
                self._finish_question()
                if text and self.li["id"]:
                    self.question = {"id": self.li["id"], "text": text, "answer": []}
            elif self.question and text:
                indent = "  " * (self.ul_depth - 2)
                self.question["answer"].append(f"{indent}- {text}")
            self.li = None

    def handle_data(self, data):
        if self.heading_text is not None:
            self.heading_text.append(data)
        elif self.li:
            self.li["text"].append(data)
        elif self.block is not None:
            self.block.append(data)

    def _finish_question(self):
        if self.question and self.question["answer"]:
            self.entries.append(
                FaqEntry(
                    section_id=self.question["id"],
                    question=self.question["text"],
                    answer="\n".join(self.question["answer"]),
                )
            )
        elif self.question:
            # A bullet with nothing under it is just text in the section
            self.lines.append(_clean(self.question["text"]))
        self.question = None

    def _finish_section(self):
        """Turn the section that just ended into an entry, unless it already
        has bullet questions."""
        heading = self.heading
        if heading and heading["id"] and len(self.entries) == self.section_start:
            lines = [
                line
                for line in self.lines
                if not line.lower().startswith("back to table of contents")
            ]
            answer = "\n".join(lines)
            if answer and "table of contents" not in heading["text"].lower():
                self.entries.append(
                    FaqEntry(
                        section_id=heading["id"],
                        question=heading["text"],
                        answer=answer,
                    )
                )
        self.lines = []
        self.section_start = len(self.entries)
        self.heading = None


def parse_faq_canvas(html: str) -> list[FaqEntry]:
    """Parse FAQ entries from canvas HTML. If a question appears more than
    once, the last copy wins."""
    parser = _CanvasFaqParser()
    parser.feed(html)
    parser.close()
    parser._finish_section()

    def key(question: str) -> str:
        return re.sub(r"[\u2018\u2019]", "'", question).lower()

    deduped = {key(entry.question): entry for entry in parser.entries}
    return list(deduped.values())


async def refresh_faq_entries() -> None:
    """Re-fetch the FAQ canvas, keeping the previous copy on failure."""
    global faq_entries, _last_refresh_failed
    canvas_id = env.transcript.faq_canvas_id
    if not canvas_id:
        return
    try:
        info = await AsyncWebClient(token=env.slack_user_token).files_info(
            file=canvas_id
        )
        file: dict = info["file"]  # type: ignore (assuming file exists)
        url = file.get("url_private_download") or file["url_private"]
        async with env.session.get(
            url, headers={"Authorization": f"Bearer {env.slack_user_token}"}
        ) as res:
            res.raise_for_status()
            html = await res.text()
        entries = parse_faq_canvas(html)
    except Exception as e:
        entries = []
        logging.error(f"Failed to fetch FAQ canvas canvas_id={canvas_id} error={e}")
    if not entries:
        if not _last_refresh_failed:
            logging.error(
                f"Couldn't read any questions from FAQ canvas {canvas_id}, keeping the old copy. Check the logs!"
            )
        _last_refresh_failed = True
        return
    _last_refresh_failed = False
    faq_entries = entries
    global _events_entry_missing
    missing = bool(env.transcript.faq_events_question) and events_entry() is None
    if missing and not _events_entry_missing:
        logging.warning(
            f"No FAQ entry matches faq_events_question={env.transcript.faq_events_question!r} "
            f"and none looks like an event list, headings={[e.question for e in entries]}"
        )
    _events_entry_missing = missing
    logging.info(f"Loaded {len(entries)} FAQ entries from canvas {canvas_id}")


def faq_link_label(entry: FaqEntry) -> str:
    """The question, escaped for use inside a Slack <url|label> link."""
    return (
        entry.question.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def faq_section_url(entry: FaqEntry) -> str:
    """Deep link to a single question in the FAQ canvas."""
    return f"{env.transcript.faq_link}?focus_section_id={entry.section_id}"


def parse_event_channels(answer: str) -> list[EventChannel]:
    """Read an "event, then its help channel" list out of an FAQ answer."""
    events: dict[str, EventChannel] = {}
    previous = ""
    for line in answer.splitlines():
        line = line.strip()
        match = CHANNEL_LINE.match(line)
        if not match:
            previous = line
            continue
        name = match["name"] or previous
        if name and match["id"] != env.slack_help_channel:
            events.setdefault(name.lower(), EventChannel(name, match["id"]))
        previous = ""
    return list(events.values())


def events_entry() -> FaqEntry | None:
    question = env.transcript.faq_events_question
    if not question:
        return None
    prefix = question.lower()
    entry = next(
        (e for e in faq_entries if e.question.lower().startswith(prefix)), None
    )
    if entry:
        return entry
    best = max(
        faq_entries, key=lambda e: len(parse_event_channels(e.answer)), default=None
    )
    if best and len(parse_event_channels(best.answer)) >= MIN_EVENTS:
        return best
    return None


def event_channels() -> list[EventChannel]:
    """The events listed in this program's FAQ canvas, or none if the program
    doesn't have such a list (the transcript's `faq_events_question`)."""
    entry = events_entry()
    return parse_event_channels(entry.answer) if entry else []


def event_suggestion(event: EventChannel) -> str:
    """The reply pointing someone to an event's help channel."""
    name = event.name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return env.transcript.event_channel_suggestion.replace("{program}", name).replace(
        "{channel}", f"<#{event.channel_id}>"
    )


def _confident_choice[T](
    response: DecisionsResponse,
    key: str,
    options: dict[str, T],
    text: str,
    require_confidence: bool = False,
) -> T | None:
    """The option the AI picked for `key`, unless it said none or wasn't confident."""
    answer = response["answers"].get(key)
    if not answer or answer["type"] != "choice":
        logging.error(
            f'AI response is missing {key} answer for text="{text}" response="{response}"'
        )
        return None
    choice = answer["choice"]
    confidence = answer.get("confidence")
    if confidence is None:
        confidence = answer.get("probabilities", {}).get(choice)
    if confidence is None and not require_confidence:
        logging.warning(
            f"{key} match has no confidence, using it anyway choice={choice!r}"
        )
    logging.info(f"{key} match choice={choice!r} confidence={confidence}")
    if choice == NO_MATCH:
        return None
    if confidence is None and require_confidence:
        return None
    if confidence is not None and confidence < env.ai_faq_min_confidence:
        return None
    return options.get(choice)


async def match_faq(text: str, not_identity_verified: bool = False) -> FaqMatch:
    """Ask the AI which FAQ entry (if any) answers the given message, and which
    event's help channel (if any) it is about.

    The model only picks from the transcript's FAQ entries and event list, so it
    can't make up an answer. `not_identity_verified` tells it the sender hasn't
    been identity verified. Only one of the entry and the
    event is returned: a specific FAQ entry wins, but the event's own channel
    beats the generic "support for events" entry. Returns an empty match if
    nothing is confident enough."""
    entries = faq_entries
    if not entries or not ai_client or not text.strip():
        return FaqMatch()

    program = env.transcript.program_name
    criteria: dict[str, StructuredGuidance | None] = {
        entry.question: entry.answer for entry in entries
    }
    criteria[NO_MATCH] = (
        "None of the FAQ entries clearly answer this message, "
        "or the message is about a personal/account-specific issue that needs a human."
    )

    state: dict = {"message": {"message_content": text}}
    instructions = f"A participant in {program} sent this support message. Which FAQ entry directly answers their question?"
    if not_identity_verified:
        state["user"] = {"identity_verified": False}
        instructions += (
            " The sender has not been identity verified; take that into account "
            "where the right answer depends on it."
        )

    questions: dict[str, ChoiceQuestion] = {
        "faq": {"type": "choice", "instructions": instructions, "criteria": criteria}
    }
    events = event_channels()
    if events:
        event_criteria: dict[str, StructuredGuidance | None] = {
            event.name: f"The message is about {event.name}." for event in events
        }
        event_criteria[NO_MATCH] = (
            "The message is a general question, is about several events, "
            "or it is not clear which one it is about."
        )
        questions["event"] = {
            "type": "choice",
            "instructions": (
                f"A participant in {program} sent this support message. If it is "
                "clearly about one specific event or program (named, or an obvious "
                "reference to it), choose that event so they can be pointed to its "
                "own help channel."
            ),
            "criteria": event_criteria,
        }

    model = env.ai_faq_model
    try:
        response = await decisions(model=model, state=state, questions=questions)
    except HTTPStatusError as e:
        logging.error(
            f'Failed to match FAQ text="{text}" error="{e}" response="{e.response.text[:200]}"'
        )
        return FaqMatch()
    except Exception as e:
        logging.error(f'Failed to match FAQ text="{text}" error="{e}"', exc_info=True)
        return FaqMatch()

    entry = _confident_choice(
        response, "faq", {entry.question: entry for entry in entries}, text
    )
    event = (
        _confident_choice(
            response,
            "event",
            {event.name: event for event in events},
            text,
            require_confidence=True,
        )
        if events
        else None
    )
    if event and (entry is None or entry is events_entry()):
        return FaqMatch(event=event)
    return FaqMatch(entry=entry)
