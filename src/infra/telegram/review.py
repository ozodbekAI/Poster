from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.infra.db.repositories import DraftRepo
from src.infra.telegram.callbacks import DraftCb
from src.infra.telegram.keyboards import review_keyboard, regen_keyboard
from src.usecases.regenerate import regenerate_draft

logger = logging.getLogger(__name__)
router = Router()


def _tg_file_url(bot_token: str, file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"


async def _safe_edit_reply_markup(cb: CallbackQuery, reply_markup) -> None:
    try:
        await cb.message.edit_reply_markup(reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _render_review_message(cb: CallbackQuery, *, draft_id: int, db: AsyncSession) -> None:
    """Re-render review message with current draft content."""
    d = await DraftRepo(db).get(draft_id)
    if not d:
        await cb.message.answer("⚠️ Draft не найден")
        return

    try:
        if d.image_paths:
            media = InputMediaPhoto(
                media=FSInputFile(d.image_paths[0]),
                caption=d.caption or "(пусто)",
                parse_mode="HTML",
            )
            await cb.message.edit_media(media=media, reply_markup=review_keyboard(d.id))
        else:
            await cb.message.edit_text(d.caption or "(пусто)", reply_markup=review_keyboard(d.id), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        logger.exception("Review: failed to update message")
        await cb.message.answer(f"⚠️ Не удалось обновить сообщение: {e}")


@router.callback_query(DraftCb.filter())
async def on_review(cb: CallbackQuery, callback_data: DraftCb, db: AsyncSession, bot: Bot):
    draft_id = int(callback_data.draft_id)
    action = (callback_data.action or "").strip()

    draft_repo = DraftRepo(db)
    d = await draft_repo.get(draft_id)
    if not d:
        await cb.answer("Draft не найден", show_alert=True)
        return

    # -----------------
    # Approve / Reject
    # -----------------
    if action == "approve":
        await cb.answer("✅ Одобрено", show_alert=False)
        await draft_repo.set_status(draft_id, "approved")
        await _safe_edit_reply_markup(cb, None)
        await cb.message.answer(f"✅ Draft #{draft_id} ОДОБРЕН (в очереди)")
        return

    if action == "reject":
        await cb.answer("❌ Отклонено", show_alert=False)
        await draft_repo.set_status(draft_id, "rejected")
        await _safe_edit_reply_markup(cb, None)
        await cb.message.answer(f"❌ Draft #{draft_id} ОТКЛОНЁН")
        return

    # -----------------
    # Regen menu open
    # -----------------
    # UX: the main button opens a menu; the menu buttons actually run regen.
    if action == "regen_menu":
        await cb.answer("Выберите вариант регенерации", show_alert=False)
        await _safe_edit_reply_markup(cb, regen_keyboard(draft_id))
        return

    # -----------------
    # Regen execution
    # -----------------
    if action in {"regen_img", "regen_cap", "regen_all"}:
        # Answer quickly, otherwise callback may expire
        await cb.answer("⏳ Регенерирую...", show_alert=False)

        # Optional reference image: try to use the photo in the current review message
        reference_urls: list[str] = []
        try:
            if cb.message and cb.message.photo:
                ph = cb.message.photo[-1]
                tg_file = await bot.get_file(ph.file_id)
                reference_urls.append(_tg_file_url(settings.telegram_bot_token, tg_file.file_path))
        except Exception:
            logger.exception("Regen: failed to build reference URL")

        ok = await regenerate_draft(
            db=db,
            draft_id=draft_id,
            mode=action,
            reference_image_urls=reference_urls or None,
        )

        if not ok:
            await cb.message.answer("⚠️ Регенерация не удалась (KIE/AI вернули ошибку или пустой результат).")
            # Return to main keyboard anyway
            await _safe_edit_reply_markup(cb, review_keyboard(draft_id))
            return

        await _render_review_message(cb, draft_id=draft_id, db=db)
        return

    await cb.answer("Неизвестное действие", show_alert=True)
