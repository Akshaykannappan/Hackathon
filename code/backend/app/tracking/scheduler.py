"""APScheduler daily recommendation digest runner.

Env-gated: disabled by default (`ENABLE_SCHEDULER=false`), never fires in tests.
When enabled, runs daily at 17:00 local time to generate recommendation digests
for users active today.
"""

import logging
from datetime import datetime, time, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.database import engine
from app.models import Event, User

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def send_daily_digests() -> None:
    """Scheduled task: generate recommendations and dispatch daily digests to active users."""
    logger.info("scheduler.digest_run_started")

    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)

    with Session(engine) as session:
        # Select users who logged event activity today
        active_user_ids = session.exec(
            select(Event.user_id)
            .where(col(Event.created_at) >= today_start)
            .distinct()
        ).all()

        if not active_user_ids:
            logger.info("scheduler.digest_skipped reason=no_active_users_today")
            return

        from app.agent.graph import run_agent

        for user_id in active_user_ids:
            user = session.get(User, user_id)
            if user is None:
                continue

            try:
                state = run_agent(session, user_id, trigger_reason="daily_digest")
                message = state.get("message", "")
                product_ids = state.get("product_ids", [])
                logger.info(
                    "scheduler.digest_sent user_id=%s email=%s products=%s message_snippet=%s",
                    user_id,
                    user.email,
                    product_ids,
                    message[:60] if message else "",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("scheduler.digest_failed user_id=%s error=%s", user_id, exc)


def start_scheduler() -> BackgroundScheduler | None:
    """Initialize and start the background scheduler if enabled by config."""
    global _scheduler

    if not settings.enable_scheduler:
        logger.info("scheduler.disabled reason=config_enable_scheduler_false")
        return None

    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="local")
    _scheduler.add_job(
        send_daily_digests,
        trigger="cron",
        hour=17,
        minute=0,
        id="daily_recommendation_digest",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("scheduler.started scheduled_time='17:00 local daily'")
    return _scheduler


def stop_scheduler() -> None:
    """Shutdown background scheduler gracefully."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler.stopped")
