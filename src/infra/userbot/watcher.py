from __future__ import annotations

import logging
import time
from typing import Set

from pyrogram import Client, filters
from pyrogram.types import Message as PyroMessage

from src.common.config import settings
from src.infra.db.base import async_session_maker
from src.infra.db.repositories import ChannelRepo

logger = logging.getLogger(__name__)

_ALLOWED_CACHE: dict[str, object] = {"ts": 0.0, "set": set()}  # type: ignore[misc]


async def _allowed_usernames(ttl_seconds: int = 30) -> Set[str]:
    """Load allowed channel usernames from DB with a small TTL cache."""
    now = time.monotonic()
    ts = float(_ALLOWED_CACHE.get("ts") or 0.0)
    cached = _ALLOWED_CACHE.get("set")
    if isinstance(cached, set) and (now - ts) < ttl_seconds:
        return cached  # type: ignore[return-value]

    async with async_session_maker() as db:
        repo = ChannelRepo(db)
        rows = await repo.list()
        allowed = {c.username.lower().lstrip("@") for c in rows if c.username}

    _ALLOWED_CACHE["ts"] = now
    _ALLOWED_CACHE["set"] = allowed
    logger.info("Userbot: loaded %d allowed channels: %s", len(allowed), sorted(list(allowed))[:20])
    return allowed


def _extract_text(msg: PyroMessage) -> str:
    return (msg.text or msg.caption or "").strip()


def setup_handlers(app: Client) -> None:
    @app.on_message(filters.channel)
    async def on_channel_post(client: Client, msg: PyroMessage):
        try:
            if not settings.ingest_bot_username:
                raise ValueError("INGEST_BOT_USERNAME is not set")

            username = (getattr(msg.chat, "username", "") or "").lower().lstrip("@")
            allowed = await _allowed_usernames()

            if allowed:
                if not username:
                    # Private channel without username — in this implementation we can't match it
                    logger.debug("Skip channel without username: chat_id=%s", getattr(msg.chat, "id", None))
                    return
                if username not in allowed:
                    return

            # If it's an album (media_group_id), forward only the item that contains caption/text.
            # This prevents duplicates while still keeping (caption + one photo).
            if msg.media_group_id and not _extract_text(msg):
                logger.debug(
                    "Skip album item without text/caption: %s msg_id=%s group=%s",
                    username or getattr(msg.chat, "id", None),
                    msg.id,
                    msg.media_group_id,
                )
                return

            text = _extract_text(msg)
            has_photo = bool(getattr(msg, "photo", None))
            logger.info(
                "Userbot: incoming post channel=%s msg_id=%s group=%s has_photo=%s text_len=%s",
                username or getattr(msg.chat, "id", None),
                msg.id,
                msg.media_group_id,
                has_photo,
                len(text),
            )

            # Prefer forward (keeps media & forward metadata). If it fails, try copy with embedded source tag.
            src_tag = f"\n\n#src:{getattr(msg.chat, 'id', 0)}:{msg.id}"
            try:
                await msg.forward(settings.ingest_bot_username)
                logger.info("Userbot: forwarded msg_id=%s from %s", msg.id, username or getattr(msg.chat, 'id', None))
            except Exception as e:
                logger.warning("Userbot: forward failed (%s). Trying copy_message.", e)
                try:
                    is_media = bool(getattr(msg, 'photo', None) or getattr(msg, 'document', None) or getattr(msg, 'video', None) or getattr(msg, 'animation', None))
                    if is_media:
                        # For media messages we can override caption to include source tag.
                        cap = _extract_text(msg)
                        cap = (cap + src_tag).strip() if cap else src_tag.strip()
                        await client.copy_message(
                            chat_id=settings.ingest_bot_username,
                            from_chat_id=getattr(msg.chat, 'id', 0),
                            message_id=msg.id,
                            caption=cap,
                        )
                        logger.info("Userbot: copied msg_id=%s from %s", msg.id, username or getattr(msg.chat, 'id', None))
                    else:
                        # Text-only: send the text with embedded source tag.
                        t = (_extract_text(msg) + src_tag).strip()
                        if t:
                            await client.send_message(settings.ingest_bot_username, t)
                except Exception as e2:
                    logger.warning("Userbot: copy/send fallback failed (%s).", e2)
                    t = (_extract_text(msg) + src_tag).strip()
                    if t:
                        try:
                            await client.send_message(settings.ingest_bot_username, t)
                        except Exception:
                            pass
        except Exception:
            logger.exception("Userbot failed in on_channel_post")
