import logging

from itsdangerous import BadSignature
from starlette.requests import Request
from starlette.responses import HTMLResponse

from nephthys.utils import helper_oauth
from nephthys.utils.env import env


async def slack_oauth_callback(req: Request):
    if not env.helper_oauth:
        return HTMLResponse("Helper OAuth is not configured", status_code=501)

    try:
        slack_id = helper_oauth.read_state(req.query_params.get("state", ""))
    except BadSignature:
        return HTMLResponse("This link is invalid or expired.", status_code=400)

    code = req.query_params.get("code")
    if not code:
        return HTMLResponse("Slack authorization was cancelled.", status_code=400)

    res = await env.slack_client.oauth_v2_access(
        client_id=env.slack_client_id or "",
        client_secret=env.slack_client_secret or "",
        code=code,
        redirect_uri=helper_oauth.redirect_uri(),
    )
    authed = res.get("authed_user") or {}
    if authed.get("id") != slack_id or not authed.get("access_token"):
        return HTMLResponse("Slack account mismatch.", status_code=403)

    await helper_oauth.save_token(slack_id, authed["access_token"])
    logging.info(f"Helper <@{slack_id}> connected Slack OAuth")
    return HTMLResponse("<h2>Connected! You can return to Slack now.</h2>")
