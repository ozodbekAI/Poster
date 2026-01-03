from __future__ import annotations

import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from src.common.config import settings
from src.infra.db.repositories import DraftRepo, SettingRepo
from src.infra.telegram.publisher import ChannelPublisher

logger = logging.getLogger(__name__)

async def publish_queue_tick(*, db: AsyncSession, bot: Bot) -> int:
    logger.info("Publish tick started")
    srepo = SettingRepo(db)
    dest = await srepo.get("DESTINATION_CHANNEL")
    destination = dest or settings.destination_channel
    if not destination:
        logger.warning("DESTINATION_CHANNEL is not set")
        return 0

    repo = DraftRepo(db)
    drafts = await repo.list_approved_unpublished(limit=settings.publish_batch_size)
    if not drafts:
        logger.info("Publish tick: queue empty")
        return 0

    publisher = ChannelPublisher(bot)
    
    bot_user = await srepo.get("EXTERNAL_BOT_USERNAME")
    btn_text = await srepo.get("EXTERNAL_BUTTON_TEXT")
    sent = 0
    for d in drafts:
        try:
            raw = d.image_paths_json or "[]"
            image_paths = json.loads(raw) if isinstance(raw, str) else []
            if not isinstance(image_paths, list):
                image_paths = []
            token = f"p_{d.id}"
            await publisher.publish(
                destination=destination,
                caption=d.caption,
                image_paths=image_paths,
                token=token,
                bot_username=bot_user or None,
                button_text=btn_text or None,
            )
            await repo.set_status(d.id, "published")
            sent += 1
        except Exception:
            logger.exception("Publish failed for draft %s", d.id)
            await repo.set_status(d.id, "failed")
    logger.info("Publish tick finished: published=%s", sent)
    return sent
