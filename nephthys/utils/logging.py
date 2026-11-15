import asyncio
import logging
import re
import sys
import time
from base64 import b64encode
from contextvars import ContextVar
from os import environ
from os import uname
from uuid import uuid4

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from nephthys.utils.env import env


async def send_heartbeat(heartbeat: str, messages: list[str] | None = None):
    if env.slack_heartbeat_channel:
        msg = await env.slack_client.chat_postMessage(
            channel=env.slack_heartbeat_channel, text=heartbeat
        )
        if messages:
            for message in messages:
                await env.slack_client.chat_postMessage(
                    channel=env.slack_heartbeat_channel,
                    text=message,
                    thread_ts=msg["ts"],
                )


# Loggers whose records must never be posted to Slack: posting to Slack uses
# these libraries, so a Slack/network failure would otherwise loop.
_SLACK_IGNORED_LOGGERS = ("slack_sdk", "aiohttp", "httpx", "opentelemetry")
_SLACK_DEDUPE_SECONDS = 60
_OUT_OF_CREDITS_DEDUPE_SECONDS = 3600
_OUT_OF_CREDITS = re.compile(
    r"\b402\b|insufficient (credits|funds|balance)|out of credits", re.IGNORECASE
)
_in_slack_handler: ContextVar[bool] = ContextVar("in_slack_handler", default=False)


class SlackHandler(logging.Handler):
    """Posts WARNING+ log records to the Slack heartbeat channel."""

    def __init__(self, level: int = logging.WARNING):
        super().__init__(level)
        self._recent: dict[tuple[str, str | None], float] = {}
        self._tasks: set[asyncio.Task] = set()

    def emit(self, record: logging.LogRecord):
        if _in_slack_handler.get() or record.name.startswith(_SLACK_IGNORED_LOGGERS):
            return
        message = record.getMessage()
        # Bolt warns about every event we have no listener for
        if record.name.startswith("slack_bolt") and message.startswith(
            "Unhandled request"
        ):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop to post from; stderr/OTEL still have it

        levelno, levelname = record.levelno, record.levelname
        detail = message + (str(record.exc_info[1]) if record.exc_info else "")
        out_of_credits = levelno >= logging.ERROR and bool(
            _OUT_OF_CREDITS.search(detail)
        )
        if out_of_credits:
            levelno, levelname = logging.WARNING, "WARNING"

        # Drop identical messages within a minute so one outage doesn't spam
        now = time.monotonic()
        self._recent = {
            k: t
            for k, t in self._recent.items()
            if now - t
            < (
                _OUT_OF_CREDITS_DEDUPE_SECONDS
                if k[1] is None
                else _SLACK_DEDUPE_SECONDS
            )
        }
        key = (record.name, None if out_of_credits else message)
        if key in self._recent:
            return
        self._recent[key] = now

        text = f"*{levelname}* `{record.name}`: {message}"[:3000]
        extra = []
        if record.exc_info:
            tb = logging.Formatter().formatException(record.exc_info)
            extra.append(f"```{tb[-2900:]}```")
        if levelno >= logging.ERROR and env.slack_maintainer_id:
            extra.append(f"cc <@{env.slack_maintainer_id}>")
        task = loop.create_task(self._post(text, extra))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _post(self, text: str, extra: list[str]):
        _in_slack_handler.set(True)
        try:
            await send_heartbeat(text, extra)
        except Exception as e:
            # Not logging: that would just come back to this handler
            print(f"Failed to post log to Slack: {e}", file=sys.stderr)


def parse_level_name(level_name: str | int) -> int:
    if isinstance(level_name, int):
        return level_name
    name = level_name.upper()
    if name == "VERBOSE":
        name = "DEBUG"
    name_to_int = logging.getLevelNamesMapping()
    try:
        return name_to_int[name]
    except KeyError:
        raise ValueError(f"Invalid log level: {level_name}")


def setup_otel_logging():
    """Set up OpenTelemetry logging, using env vars for configuration."""
    resource_attributes = {
        "service.name": env.otel_service_name,
        "service.instance.id": uuid4().hex,
        "deployment.environment": env.environment,
        "host.name": uname().nodename,
    }
    commit_hash = environ.get("SOURCE_COMMIT")
    container_name = environ.get("COOLIFY_CONTAINER_NAME")
    deployment_url = environ.get("COOLIFY_URL")
    deployment_fqdn = environ.get("COOLIFY_FQDN")
    if commit_hash:
        resource_attributes["service.version"] = commit_hash
    if container_name:
        resource_attributes["container.name"] = container_name
    if deployment_url:
        resource_attributes["deployment.url"] = deployment_url
    if deployment_fqdn:
        resource_attributes["deployment.fqdn"] = deployment_fqdn
    provider = LoggerProvider(resource=Resource.create(resource_attributes))
    set_logger_provider(provider)

    auth_header = (
        "Basic " + b64encode(env.otel_logs_basic_auth.encode()).decode()
        if env.otel_logs_basic_auth
        else None
    )
    otlp_exporter = OTLPLogExporter(
        endpoint=env.otel_logs_url,
        headers={"Authorization": auth_header} if auth_header else {},
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter))

    # Don't allow DEBUG logs to be sent via HTTP, because that creates infinite recursive HTTP request logs
    log_level = max(parse_level_name(env.log_level_otel), logging.INFO)
    handler = LoggingHandler(level=log_level, logger_provider=provider)

    logging.getLogger().addHandler(handler)
    logging.info("Initialised OpenTelemetry logs exporter from environment variables")
