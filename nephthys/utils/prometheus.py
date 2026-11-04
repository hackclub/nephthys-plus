import logging

from slack_sdk.errors import SlackApiError

from nephthys.utils import helper_oauth
from nephthys.utils.env import env


async def can_delete_others() -> bool:
    return bool(env.prometheus_api_key) or await env.workspace_admin_available()


async def delete_message(
    ts: str, channel: str, reason: str, actor_slack_id: str | None = None
) -> bool:
    """Delete a Slack message.

    Returns True if the message was deleted, False otherwise.
    """
    if actor_slack_id and env.helper_oauth:
        token = await helper_oauth.get_token(actor_slack_id)
        if token:
            try:
                await env.slack_client.chat_delete(channel=channel, ts=ts, token=token)
                return True
            except SlackApiError as e:
                error = e.response["error"]
                if error == "message_not_found":
                    return True
                if error in ("token_revoked", "invalid_auth", "account_inactive"):
                    await helper_oauth.forget_token(actor_slack_id)

    if env.prometheus_api_key:
        async with env.session.post(
            f"{env.prometheus_base_url}/api/v1/messages/delete",
            headers={"Authorization": f"Bearer {env.prometheus_api_key}"},
            json={"ts": ts, "reason": reason},
        ) as resp:
            body = await resp.json()
            failed = body.get("failed") or []
            if any(f.get("error") == "message_not_found" for f in failed):
                return True
            if resp.status != 200 or ts not in body.get("deleted", []):
                logging.error(f"Prometheus failed to delete message ts={ts}: {body}")
                return False
            return True

    if not await env.workspace_admin_available():
        logging.error(
            f"Cannot delete message ts={ts}: no PROMETHEUS_API_KEY and "
            "SLACK_USER_TOKEN lacks workspace admin"
        )
        return False

    try:
        await env.slack_client.chat_delete(
            channel=channel,
            ts=ts,
            token=env.slack_user_token,
            broadcast_delete=True,
        )
        return True
    except Exception as e:
        logging.error(f"chat_delete failed for ts={ts} in {channel}: {e}")
        return False


async def delete_thread(thread_ts: str, channel: str, reason: str) -> bool:
    """Delete a whole thread: the root message and every reply.

    Uses Prometheus' single thread endpoint (one audit log line) when an API
    key is set, otherwise falls back to deleting each message individually.
    """
    if env.prometheus_api_key:
        try:
            async with env.session.post(
                f"{env.prometheus_base_url}/api/v1/threads/delete",
                headers={"Authorization": f"Bearer {env.prometheus_api_key}"},
                json={"thread_ts": thread_ts, "reason": reason},
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status != 200 or not body.get("ok"):
                    logging.error(
                        f"Prometheus failed to delete thread ts={thread_ts}: {body}"
                    )
                    return False
                return True
        except Exception:
            logging.exception(f"Prometheus failed to delete thread ts={thread_ts}")
            return False

    replies = await env.slack_client.conversations_replies(
        channel=channel, ts=thread_ts
    )
    ok = True
    # Replies first, root last: deleting the root can orphan the reply fetch.
    for msg in reversed(replies.get("messages", [])):
        if "ts" in msg and not await delete_message(msg["ts"], channel, reason):
            ok = False
    return ok
