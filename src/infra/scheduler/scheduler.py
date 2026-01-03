from __future__ import annotations

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot

from src.common.config import settings
from src.infra.db.base import async_session_maker
from src.usecases.publish_queue import publish_queue_tick

logger = logging.getLogger(__name__)

def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    if settings.publish_every_minutes and settings.publish_every_minutes > 0:
        scheduler.add_job(
            func=_publish_job,
            trigger=IntervalTrigger(minutes=settings.publish_every_minutes),
            kwargs={"bot": bot},
            id="publish_queue",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    return scheduler

async def _publish_job(bot: Bot) -> None:
    async with async_session_maker() as db:
        n = await publish_queue_tick(db=db, bot=bot)
        if n:
            logger.info("Published %s post(s)", n)
