from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from statistics import fmean
from typing import TypedDict

from nephthys.database.enums import TicketStatus
from nephthys.database.tables import Ticket
from nephthys.database.tables import User
from nephthys.utils.old_tickets import get_unanswered_tickets
from nephthys.utils.ticket_methods import get_question_message_link


class LeaderboardEntry(TypedDict):
    user: User
    count: int


def leaderboard_name(entry: LeaderboardEntry) -> str:
    user = entry["user"]
    return f"<@{user.slack_id}>" + ("" if user.helper else " (not helper)")


async def build_leaderboard(tickets: list[Ticket]) -> list[LeaderboardEntry]:
    counts = Counter(
        t.closed_by for t in tickets if t.closed_by and t.closed_by != t.opened_by
    )
    if not counts:
        return []
    users = await User.objects().where(User.id.is_in(list(counts)))
    board: list[LeaderboardEntry] = [{"user": u, "count": counts[u.id]} for u in users]
    return sorted(board, key=lambda entry: entry["count"], reverse=True)


class OldestUnansweredTicket(TypedDict):
    id: int
    created_at: str
    age_minutes: float
    link: str


@dataclass
class OverallStatsResult:
    tickets_total: int
    tickets_open: int
    tickets_closed: int
    tickets_in_progress: int
    helpers_leaderboard: list[LeaderboardEntry]
    mean_hang_time_minutes_unresolved: float | None
    mean_hang_time_minutes_all: float | None
    mean_resolution_time_minutes: float | None
    oldest_unanswered_ticket: OldestUnansweredTicket | None

    def as_dict(self) -> dict:
        # Warning: Changing these keys will break the stats API
        # Note: These fields are documented for end users in api.md
        return {
            "tickets_total": self.tickets_total,
            "tickets_open": self.tickets_open,
            "tickets_closed": self.tickets_closed,
            "tickets_in_progress": self.tickets_in_progress,
            "helpers_leaderboard": [
                {
                    "id": entry["user"].id,
                    "slack_id": entry["user"].slack_id,
                    "count": entry["count"],
                }
                for entry in self.helpers_leaderboard
            ],
            "mean_hang_time_minutes_unresolved": self.mean_hang_time_minutes_unresolved,
            "mean_hang_time_minutes_all": self.mean_hang_time_minutes_all,
            "mean_resolution_time_minutes": self.mean_resolution_time_minutes,
            "oldest_unanswered_ticket": self.oldest_unanswered_ticket,
        }


def calculate_hang_times(
    tickets: list[Ticket], include_closed_tickets: bool
) -> list[float]:
    hang_times = []
    for tkt in tickets:
        if not include_closed_tickets and tkt.status == TicketStatus.CLOSED:
            continue
        if not tkt.assigned_at:
            continue
        hang_times.append((tkt.assigned_at - tkt.created_at).total_seconds() / 60)
    return hang_times


WAIT_ESTIMATE_DAYS = 7
WAIT_ESTIMATE_MIN_TICKETS = 5


async def average_wait_minutes(
    days: int = WAIT_ESTIMATE_DAYS, min_tickets: int = WAIT_ESTIMATE_MIN_TICKETS
) -> float | None:
    """Average minutes someone has waited for a first reply from anyone but the poster,
    over recent tickets, without the fastest and slowest 7%.

    Tickets that got a reply count how long they waited. Tickets still waiting
    count up to now, so a growing backlog pushes the estimate up. Tickets closed
    without any reply (e.g. the poster resolved it themselves) didn't wait
    on anyone, so they're left out. Returns None if there are too few tickets to
    say anything useful.
    """
    now = datetime.now(UTC)
    tickets = await Ticket.objects().where(
        Ticket.created_at >= now - timedelta(days=days)
    )
    waits: list[float] = []
    for tkt in tickets:
        if tkt.first_reply_at:
            waits.append((tkt.first_reply_at - tkt.created_at).total_seconds() / 60)
        elif tkt.status != TicketStatus.CLOSED:
            waits.append((now - tkt.created_at).total_seconds() / 60)
    if len(waits) < min_tickets:
        return None
    waits.sort()
    trim = int(len(waits) * 0.07)
    return fmean(waits[trim : len(waits) - trim])


def format_wait(minutes: float) -> str:
    """A rough, human wait time like "12 minutes" or "3 hours"."""
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        n = round(minutes)
        return f"{n} minute{'' if n == 1 else 's'}"
    hours = minutes / 60
    if hours < 48:
        n = round(hours)
        return f"{n} hour{'' if n == 1 else 's'}"
    return f"{round(hours / 24)} days"


def calculate_resolution_times(tickets: list[Ticket]) -> list[float]:
    resolution_times = []
    for tkt in tickets:
        if not tkt.closed_at:
            continue
        resolution_times.append((tkt.closed_at - tkt.created_at).total_seconds() / 60)
    return resolution_times


async def calculate_overall_stats() -> OverallStatsResult:
    tickets = await Ticket.objects() or []

    helpers_leaderboard = await build_leaderboard(tickets)

    total_open = len([t for t in tickets if t.status == TicketStatus.OPEN])
    total_in_progress = len(
        [t for t in tickets if t.status == TicketStatus.IN_PROGRESS]
    )
    total_closed = len([t for t in tickets if t.status == TicketStatus.CLOSED])
    total = len(tickets)

    hang_times_unresolved = calculate_hang_times(tickets, include_closed_tickets=False)
    hang_times_all = calculate_hang_times(tickets, include_closed_tickets=True)
    resolution_times = calculate_resolution_times(tickets)

    oldest_unanswered_tickets = await get_unanswered_tickets()
    oldest_unanswered_ticket = (
        oldest_unanswered_tickets[0] if oldest_unanswered_tickets else None
    )
    now = datetime.now().astimezone()
    oldest_unanswered_ticket_info = (
        OldestUnansweredTicket(
            id=oldest_unanswered_ticket.id,
            created_at=oldest_unanswered_ticket.created_at.isoformat(),
            age_minutes=(now - oldest_unanswered_ticket.created_at).total_seconds()
            / 60,
            link=get_question_message_link(oldest_unanswered_ticket),
        )
        if oldest_unanswered_ticket
        else None
    )

    return OverallStatsResult(
        tickets_total=total,
        tickets_open=total_open,
        tickets_closed=total_closed,
        tickets_in_progress=total_in_progress,
        helpers_leaderboard=helpers_leaderboard,
        mean_hang_time_minutes_unresolved=(
            fmean(hang_times_unresolved) if hang_times_unresolved else None
        ),
        mean_hang_time_minutes_all=fmean(hang_times_all) if hang_times_all else None,
        mean_resolution_time_minutes=(
            fmean(resolution_times) if resolution_times else None
        ),
        oldest_unanswered_ticket=oldest_unanswered_ticket_info,
    )


@dataclass
class DailyStatsResult:
    """Processed statistics for a time interval
    (usually 24h but doesn't have to be)"""

    new_tickets_total: int
    new_tickets_now_closed: int
    new_tickets_still_open: int
    new_tickets_in_progress: int
    closed_today: int
    closed_today_from_today: int
    assigned_today_in_progress: int
    helpers_leaderboard: list[LeaderboardEntry]
    # Mean time to response for tickets created today and currently in-progress
    mean_hang_time_minutes_unresolved: float | None
    # Mean time to response for all tickets created today
    mean_hang_time_minutes_all: float | None
    # Mean time to resolution for tickets created today
    mean_resolution_time_minutes: float | None

    def as_dict(self) -> dict:
        # Warning: Changing these keys will break the stats API
        # Note: These fields are documented for end users in api.md
        return {
            "new_tickets_total": self.new_tickets_total,
            "new_tickets_now_closed": self.new_tickets_now_closed,
            "new_tickets_still_open": self.new_tickets_still_open,
            "new_tickets_in_progress": self.new_tickets_in_progress,
            "closed_today": self.closed_today,
            "closed_today_from_today": self.closed_today_from_today,
            "assigned_today_in_progress": self.assigned_today_in_progress,
            "helpers_leaderboard": [
                {
                    "id": entry["user"].id,
                    "slack_id": entry["user"].slack_id,
                    "count": entry["count"],
                }
                for entry in self.helpers_leaderboard
            ],
            "mean_hang_time_minutes_unresolved": self.mean_hang_time_minutes_unresolved,
            "mean_hang_time_minutes_all": self.mean_hang_time_minutes_all,
            "mean_resolution_time_minutes": self.mean_resolution_time_minutes,
        }


async def calculate_daily_stats(
    start_time: datetime, end_time: datetime
) -> DailyStatsResult:
    tickets = await Ticket.objects() or []
    tickets_created_today = [
        t for t in tickets if start_time <= t.created_at < end_time
    ]

    helpers_leaderboard = await build_leaderboard(
        [t for t in tickets if t.closed_at and start_time <= t.closed_at < end_time]
    )

    new_tickets_total = len(tickets_created_today)
    new_tickets_now_closed = len(
        [t for t in tickets_created_today if t.status == TicketStatus.CLOSED]
    )
    new_tickets_still_open = len(
        [t for t in tickets_created_today if t.status == TicketStatus.OPEN]
    )
    new_tickets_in_progress = len(
        [t for t in tickets_created_today if t.status == TicketStatus.IN_PROGRESS]
    )
    tickets_closed_today = [
        t
        for t in tickets
        if t.status == TicketStatus.CLOSED
        and t.closed_at
        and start_time <= t.closed_at < end_time
    ]
    closed_today = len(tickets_closed_today)
    closed_today_from_today = len(
        [t for t in tickets_closed_today if start_time <= t.created_at < end_time]
    )
    assigned_today_in_progress = len(
        [
            t
            for t in tickets
            if t.assigned_at
            and start_time <= t.assigned_at < end_time
            and t.status == TicketStatus.IN_PROGRESS
        ]
    )

    hang_times_current = calculate_hang_times(
        tickets_created_today, include_closed_tickets=False
    )
    hang_times_all = calculate_hang_times(
        tickets_created_today, include_closed_tickets=True
    )
    resolution_times = calculate_resolution_times(tickets_created_today)
    hang_time_current = fmean(hang_times_current) if hang_times_current else None
    hang_time_all = fmean(hang_times_all) if hang_times_all else None
    resolution_time = fmean(resolution_times) if resolution_times else None

    return DailyStatsResult(
        closed_today=closed_today,
        closed_today_from_today=closed_today_from_today,
        assigned_today_in_progress=assigned_today_in_progress,
        helpers_leaderboard=helpers_leaderboard,
        new_tickets_total=new_tickets_total,
        new_tickets_now_closed=new_tickets_now_closed,
        new_tickets_in_progress=new_tickets_in_progress,
        new_tickets_still_open=new_tickets_still_open,
        mean_hang_time_minutes_unresolved=hang_time_current,
        mean_hang_time_minutes_all=hang_time_all,
        mean_resolution_time_minutes=resolution_time,
    )
