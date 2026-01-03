from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from src.common.logging import setup_logging
from src.common.config import settings
from src.infra.db.init_db import init_db
from src.infra.telegram.middlewares import DbSessionMiddleware
from src.infra.telegram.handlers.ingest import router as ingest_router
from src.infra.telegram.handlers.panel import router as panel_router
from src.infra.telegram.review import router as review_router
from src.infra.scheduler.scheduler import build_scheduler

logger = logging.getLogger(__name__)

async def main() -> None:
    setup_logging()
    await init_db()

    bot = Bot(token=settings.telegram_bot_token)  # no parse_mode to avoid HTML entity issues

    # Lightweight sanity checks (do not fail startup; log actionable diagnostics)
    try:
        me = await bot.get_me()
        logger.info("Admin bot: running as @%s (id=%s)", me.username, me.id)
    except Exception as e:
        logger.warning("Admin bot: get_me failed: %s", e)

    for name, chat_id in (
        ("ADMIN_REVIEW_CHAT_ID", settings.admin_review_chat_id),
        ("DESTINATION_CHANNEL", settings.destination_channel),
    ):
        if not chat_id:
            continue
        try:
            chat = await bot.get_chat(chat_id)
            logger.info("Admin bot: %s доступен: id=%s type=%s", name, chat.id, chat.type)
        except Exception as e:
            logger.error(
                "Admin bot: %s недоступен (%s). Проверьте: бот добавлен в чат/канал и имеет права. Ошибка: %s",
                name,
                chat_id,
                e,
            )
    dp = Dispatcher()
    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    dp.include_router(panel_router)
    dp.include_router(ingest_router)
    dp.include_router(review_router)

    scheduler = build_scheduler(bot)
    scheduler.start()

    logger.info("Admin bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
