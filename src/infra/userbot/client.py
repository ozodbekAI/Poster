from __future__ import annotations

from pyrogram import Client
from src.common.config import settings


def build_userbot() -> Client:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")

    session_string = getattr(settings, "telegram_session_string", None) or None
    use_string = bool(session_string)

    return Client(
        name=settings.telegram_session_file,
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_string=session_string,
        in_memory=use_string,
        workdir=None if use_string else "data",
    )
