from __future__ import annotations

from io import BytesIO
from typing import Optional

from aiogram import Bot
from aiogram.types import Message


def extract_best_image_file_id(message: Message) -> Optional[str]:
    if message.photo:
        return message.photo[-1].file_id
    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        return message.document.file_id
    return None


async def tg_file_id_to_bytes(bot: Bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    buf = BytesIO()
    await bot.download_file(tg_file.file_path, destination=buf)
    return buf.getvalue()
