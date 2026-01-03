from __future__ import annotations

import logging
from aiogram import Bot
from aiogram.types import FSInputFile
from src.common.deeplink import make_external_bot_url
from src.common.config import settings
from src.infra.telegram.keyboards import url_keyboard

logger = logging.getLogger(__name__)

# Telegram API limit for photo captions is 1024 characters.
_CAPTION_LIMIT = 1024


def _split_caption(text: str) -> tuple[str, str | None]:
    """Return (caption_for_photo, full_text_or_none)."""
    t = (text or "").strip()
    if len(t) <= _CAPTION_LIMIT:
        return t, None
    head = (t[: _CAPTION_LIMIT - 1].rstrip() + "…")
    return head, t

class ChannelPublisher:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def publish(
        self,
        *,
        destination: str,
        caption: str,
        image_paths: list[str],
        token: str,
        bot_username: str | None = None,
        button_text: str | None = None,
    ) -> None:
        bname = (bot_username or settings.external_bot_username).lstrip("@")
        btext = button_text or settings.external_button_text
        url = make_external_bot_url(bname, token)

        cap_for_photo, full_text = _split_caption(caption)

        if not image_paths:
            # For text-only posts Telegram allows much longer messages.
            await self.bot.send_message(destination, full_text or cap_for_photo, reply_markup=url_keyboard(btext, url))
            return

        msg = await self.bot.send_photo(
            chat_id=destination,
            photo=FSInputFile(image_paths[0]),
            caption=cap_for_photo,
            reply_markup=url_keyboard(btext, url),
        )

        # If caption was longer than 1024, send the full text as a follow-up message.
        if full_text:
            try:
                await self.bot.send_message(chat_id=destination, text=full_text, reply_to_message_id=msg.message_id)
            except Exception as e:
                logger.warning("Failed to send full caption as follow-up message: %s", e)

        for p in image_paths[1:]:
            try:
                await self.bot.send_photo(chat_id=destination, photo=FSInputFile(p), reply_to_message_id=msg.message_id)
            except Exception as e:
                logger.warning("Failed to send extra photo: %s", e)
