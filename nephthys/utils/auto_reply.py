import re

# "Where do I find my Slack ID" and similar questions, which helpers answer
# over and over. Matches if the question contains "slack" and "id", or
# "find" and "slack", or a "where/what/how ... user/member id" phrase.
SLACK_ID_PATTERNS = [
    re.compile(r"\bslack\b.*\bids?\b|\bids?\b.*\bslack\b", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"\bfind(?:ing)?\b.*\bslack\b|\bslack\b.*\bfind(?:ing)?\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"\bslack\s?ids?\b", re.IGNORECASE),
    re.compile(
        r"\b(?:where|what|how)\b[^.?!\n]{0,40}\b(?:user|member)\s?id\b",
        re.IGNORECASE,
    ),
]


def matches_slack_id_question(text: str) -> bool:
    """Whether a help question is asking how to find a Slack ID."""
    return any(pattern.search(text) for pattern in SLACK_ID_PATTERNS)
