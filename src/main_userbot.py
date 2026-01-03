from __future__ import annotations

import asyncio
import logging

from src.common.logging import setup_logging
from src.infra.db.init_db import init_db
from src.infra.userbot.client import build_userbot
from src.infra.userbot.watcher import setup_handlers

logger = logging.getLogger(__name__)

def main() -> None:
    setup_logging()
    asyncio.get_event_loop().run_until_complete(init_db())

    app = build_userbot()
    setup_handlers(app)
    logger.info("Userbot started")
    app.run()

if __name__ == "__main__":
    main()
