import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any
from typing import Literal
from typing import NotRequired
from typing import TypedDict

import httpx
from openai import AsyncOpenAI

from nephthys.utils.env import get_environ

type StructuredGuidance = str | dict[str, Any] | list[Any]

DEFAULT_BASE_URL = "https://ai.hackclub.com/proxy/v1"

# HACK_CLUB_AI_* are the old names, still read so existing deployments keep working
api_key = get_environ("AI_API_KEY") or get_environ("HACK_CLUB_AI_API_KEY")
base_url = (
    get_environ("AI_BASE_URL")
    or get_environ("HACK_CLUB_AI_BASE_URL")
    or DEFAULT_BASE_URL
).rstrip("/")

ai_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=api_key, base_url=base_url) if api_key else None
)


def provider_routing(model: str) -> dict[str, Any]:
    """Extra request body that pins Anthropic models to Anthropic's own API
    (the Hack Club AI proxy passes it on to OpenRouter). Other models are
    routed as usual."""
    if model.startswith("anthropic/"):
        return {"provider": {"only": ["anthropic"], "allow_fallbacks": False}}
    return {}


HEALTH_TTL = 60
HEALTH_TIMEOUT = 3
_health: tuple[float, bool] | None = None


async def ai_available() -> bool:
    """Whether the AI provider is reachable. Cached for HEALTH_TTL seconds."""
    global _health
    if not ai_client:
        return False
    now = time.monotonic()
    if _health is not None and now - _health[0] < HEALTH_TTL:
        return _health[1]
    try:
        response = await _http_client.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=HEALTH_TIMEOUT,
        )
        up = response.status_code < 500
    except httpx.HTTPError:
        up = False
    if _health is None or _health[1] != up:
        logging.warning("AI provider is %s", "up" if up else "down")
    _health = (now, up)
    return up


class ChoiceQuestion(TypedDict):
    type: Literal["choice"]
    instructions: StructuredGuidance
    criteria: Mapping[str, StructuredGuidance | None]


class ChoiceAnswer(TypedDict):
    type: Literal["choice"]
    choice: str
    confidence: NotRequired[float]
    probabilities: NotRequired[dict[str, float]]


class DecisionsUsage(TypedDict):
    input_tokens: int
    output_tokens: int


class DecisionsResponse(TypedDict):
    model: str
    answers: dict[str, ChoiceAnswer]
    usage: DecisionsUsage


_http_client = httpx.AsyncClient(timeout=60)


async def decisions(
    model: str,
    state: str | dict | list,
    questions: dict[str, ChoiceQuestion],
) -> DecisionsResponse:
    """Asks Typesafe's Jev model (System One) to answer multiple-choice questions.

    Hack Club AI proxies this at `<AI_BASE_URL>/jev/systemone`.
    Raises `httpx.HTTPStatusError` on API error."""
    if not api_key:
        raise RuntimeError("AI_API_KEY is not set")
    for attempt in range(3):
        try:
            response = await _http_client.post(
                f"{base_url}/jev/systemone",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "state": state, "questions": questions},
            )
        except httpx.TransportError:
            if attempt == 2:
                raise
        else:
            if response.status_code < 500 or attempt == 2:
                break
        await asyncio.sleep(0.5 * 2**attempt)
    else:
        raise RuntimeError("unreachable")
    response.raise_for_status()
    return response.json()
