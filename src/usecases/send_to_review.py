from __future__ import annotations
import json
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Bot

from src.common.config import settings
from src.infra.db.repositories import DraftRepo, SettingRepo
from src.infra.telegram.notifier import AdminNotifier

async def send_to_review(*, db: AsyncSession, bot: Bot, draft_id: int) -> None:
    repo = DraftRepo(db)
    d = await repo.get(draft_id)
    if not d:
        return
    srepo = SettingRepo(db)
    v = await srepo.get("ADMIN_REVIEW_CHAT_ID")
    chat_id = int(v) if v else (settings.admin_review_chat_id or 0)
    if not chat_id:
        raise ValueError("ADMIN_REVIEW_CHAT_ID is not set")

    image_paths = json.loads(d.image_paths_json)
    notifier = AdminNotifier(bot)
    msg_id = await notifier.send_draft(
        chat_id=chat_id,
        draft_id=d.id,
        caption=d.caption,
        image_paths=image_paths,
    )
    await repo.set_review_message(d.id, chat_id=chat_id, message_id=msg_id)
