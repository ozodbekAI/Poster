from __future__ import annotations

import logging
from aiogram import Router, Bot, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.usecases.ingest_and_build_draft import ingest_and_build_draft
from src.usecases.send_to_review import send_to_review

logger = logging.getLogger(__name__)
router = Router()

def _extract_forward_source(message: Message) -> tuple[int, int] | None:
    if message.forward_from_chat and message.forward_from_message_id:
        return message.forward_from_chat.id, message.forward_from_message_id
    if getattr(message, "forward_origin", None):
        origin = message.forward_origin
        chat = getattr(origin, "chat", None)
        mid = getattr(origin, "message_id", None)
        if chat and mid:
            return chat.id, mid
    return None

def _extract_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


async def _extract_image_urls(message: Message, bot: Bot, *, max_images: int = 3) -> list[str]:

    urls: list[str] = []

    if message.photo:
        photo = message.photo[-1]
        tg_file = await bot.get_file(photo.file_id)
        urls.append(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{tg_file.file_path}")
        return urls

    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        tg_file = await bot.get_file(message.document.file_id)
        urls.append(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{tg_file.file_path}")
        return urls

    return urls

@router.message()
async def ingest_any(message: Message, db: AsyncSession, bot: Bot):
    if settings.userbot_sender_id and message.from_user and message.from_user.id != settings.userbot_sender_id:
        return

    if message.chat.type != "private":
        return

    text = _extract_text(message)

    src = _extract_forward_source(message)
    if not src:
        return

    source_chat_id, source_message_id = src

    try:
        image_urls = await _extract_image_urls(message, bot, max_images=settings.kie_images_count)
        if not text and not image_urls:
            return
        draft_id = await ingest_and_build_draft(
            db=db,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            original_text=text or "",
            source_image_urls=image_urls or None,
        )
        await send_to_review(db=db, bot=bot, draft_id=draft_id)
        await message.answer(f"✅ Принято. Draft #{draft_id} отправлен на модерацию.")
    except Exception as e:
        logger.exception("Ingest failed")
        await message.answer(f"⚠️ Ошибка ingest: {e}")
