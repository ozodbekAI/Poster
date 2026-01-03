from __future__ import annotations
import logging
from src.infra.db.base import engine, Base

logger = logging.getLogger(__name__)

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB ready")
