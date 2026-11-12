import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from nephthys.database.enums import FeedbackRating
from nephthys.database.tables import Feedback
from nephthys.database.tables import NpsAnchor
from nephthys.utils.env import env

NPS_DAYS = 14


def rating_for(score: int) -> FeedbackRating:
    if score >= 9:
        return FeedbackRating.GREAT
    if score >= 7:
        return FeedbackRating.OKAY
    return FeedbackRating.NOT_GOOD


async def nps_text() -> str:
    since = datetime.now(timezone.utc) - timedelta(days=NPS_DAYS)
    scores = [
        row["score"]
        for row in await Feedback.select(Feedback.score).where(
            Feedback.score.is_not_null() & (Feedback.created_at > since)
        )
    ]
    promoters = sum(s >= 9 for s in scores)
    detractors = sum(s <= 6 for s in scores)
    nps = round(100 * (promoters - detractors) / len(scores)) if scores else "n/a"
    return (
        f"*Net Promoter Score: {nps}*\n"
        f"{len(scores)} responses: {promoters} promoters, "
        f"{len(scores) - promoters - detractors} passives, {detractors} detractors"
    )


async def update_nps_anchor(repost: bool = False):
    channel = env.feedback_channel_id
    if not channel:
        return
    try:
        text = await nps_text()
        old = await NpsAnchor.objects().where(NpsAnchor.channel_id == channel).first()
        if old and not repost:
            await env.slack_client.chat_update(
                channel=channel, ts=old.message_ts, text=text
            )
            return
        msg = await env.slack_client.chat_postMessage(channel=channel, text=text)
        await NpsAnchor.delete().where(NpsAnchor.channel_id == channel)
        await NpsAnchor.insert(NpsAnchor(channel_id=channel, message_ts=msg["ts"]))
        try:
            await env.slack_client.pins_add(channel=channel, timestamp=msg["ts"])
        except Exception as e:
            logging.error(f"Failed to pin NPS anchor: {e!r}")
        if old:
            try:
                await env.slack_client.pins_remove(
                    channel=channel, timestamp=old.message_ts
                )
            except Exception as e:
                logging.warning(f"Failed to unpin old NPS anchor: {e!r}")
            try:
                await env.slack_client.chat_delete(channel=channel, ts=old.message_ts)
            except Exception as e:
                logging.warning(f"Failed to delete old NPS anchor: {e!r}")
    except Exception as e:
        logging.error(f"Failed to update NPS anchor: {e!r}")
