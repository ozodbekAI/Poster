from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from src.infra.telegram.keyboards import review_keyboard

logger = logging.getLogger(__name__)

PHOTO_CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


class AdminNotifier:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_draft(self, *, chat_id: int, draft_id: int, caption: str, image_paths: list[str]) -> int:
        if not chat_id:
            raise ValueError("ADMIN_REVIEW_CHAT_ID is not set")

        if image_paths:
            img_path = image_paths[0]
            if not Path(img_path).exists():
                logger.warning("Image path does not exist: %s", img_path)
            msg = await self.bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(img_path),
                caption=_clip(caption, PHOTO_CAPTION_LIMIT),
                reply_markup=review_keyboard(draft_id),
            )
            return msg.message_id

        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=_clip(caption, TEXT_LIMIT) or f"Draft #{draft_id}",
            reply_markup=review_keyboard(draft_id),
        )
        return msg.message_id
