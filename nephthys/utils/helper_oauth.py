from urllib.parse import urlencode

from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer

from nephthys.database.tables import HelperToken
from nephthys.database.tables import User
from nephthys.utils.env import env


def redirect_uri() -> str:
    return f"{env.base_url}/slack/oauth/callback"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(env.slack_client_secret or "", salt="helper-oauth")


def _fernet() -> Fernet:
    return Fernet(env.token_encryption_key or "")


def authorize_url(slack_id: str) -> str:
    return "https://slack.com/oauth/v2/authorize?" + urlencode(
        {
            "client_id": env.slack_client_id,
            "user_scope": "chat:write",
            "redirect_uri": redirect_uri(),
            "state": _serializer().dumps(slack_id),
        }
    )


def connect_text(slack_id: str) -> str:
    return (
        f"<{authorize_url(slack_id)}|Connect your Slack account> "
        "so macros can delete your trigger messages."
    )


async def needs_connect(slack_id: str) -> bool:
    if not env.helper_oauth:
        return False
    if env.prometheus_api_key or await env.workspace_admin_available():
        return False
    user = await User.objects().get(User.slack_id == slack_id)
    return bool(user and user.helper and not await get_token(slack_id))


def read_state(state: str) -> str:
    return _serializer().loads(state, max_age=7 * 24 * 3600)


async def save_token(slack_id: str, token: str) -> None:
    user = await User.objects().get_or_create(User.slack_id == slack_id)
    await HelperToken.delete().where(HelperToken.user == user.id)
    await HelperToken.insert(
        HelperToken(
            user=user.id, access_token=_fernet().encrypt(token.encode()).decode()
        )
    )


async def get_token(slack_id: str) -> str | None:
    row = (
        await HelperToken.select(HelperToken.access_token)
        .where(HelperToken.user.slack_id == slack_id)
        .first()
    )
    return _fernet().decrypt(row["access_token"].encode()).decode() if row else None


async def forget_token(slack_id: str) -> None:
    await HelperToken.delete().where(HelperToken.user.slack_id == slack_id)
