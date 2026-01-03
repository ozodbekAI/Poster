from __future__ import annotations

import logging
from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings, admin_ids
from src.infra.db.repositories import AdminRepo, ChannelRepo, PromptTokenRepo, SettingRepo, DraftRepo
from src.infra.telegram.callbacks import PanelCb, ChannelCb, PromptCb, SettingsCb
from src.infra.telegram.keyboards import (
    main_menu_keyboard, channels_keyboard, prompts_keyboard, settings_keyboard, manual_confirm_kb, back_to_menu_kb, PAGE_SIZE
    
)
from aiogram.filters import CommandStart, StateFilter
from src.usecases.ingest_and_build_draft import ingest_and_build_draft
from src.usecases.send_to_review import send_to_review
from src.infra.db.models import Draft

logger = logging.getLogger(__name__)
router = Router()


class ManualPostStates(StatesGroup):
    waiting_text = State()
    waiting_confirm = State()


async def _ensure_admin(db: AsyncSession, user_id: int) -> bool:
    repo = AdminRepo(db)
    # If explicit admin ids configured, sync them into DB and use them as source of truth.
    ids = admin_ids()
    if ids:
        for uid in ids:
            await repo.add(uid)
    admins = await repo.list()
    if not admins:
        # bootstrap first admin
        await repo.add(user_id)
        return True
    return await repo.is_admin(user_id)


@router.message(CommandStart())
async def start(message: Message, db: AsyncSession):
    uid = message.from_user.id if message.from_user else 0
    if not await _ensure_admin(db, uid):
        return
    await message.answer(
        "Админ-панель. Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(PanelCb.filter())
async def panel_nav(cb: CallbackQuery, callback_data: PanelCb, db: AsyncSession, state: FSMContext):
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return

    action = callback_data.action
    page = max(callback_data.page, 0)

    if action == "menu":
        await state.clear()
        await cb.message.edit_text("Админ-панель. Выберите действие:", reply_markup=main_menu_keyboard())
        await cb.answer()
        return

    if action == "channels":
        repo = ChannelRepo(db)
        rows = await repo.list()
        total = len(rows)
        start_i = page * PAGE_SIZE
        slice_ = rows[start_i:start_i+PAGE_SIZE]
        chans = [c.username for c in slice_]
        text = f"Каналы-источники (всего {total})."
        await cb.message.edit_text(text, reply_markup=channels_keyboard(channels=chans, page=page, total=total))
        await cb.answer()
        return

    if action == "prompts":
        repo = PromptTokenRepo(db)
        total = await repo.count()
        offset = page * PAGE_SIZE
        rows = await repo.list_page(offset=offset, limit=PAGE_SIZE)
        tokens = [r.token for r in rows]
        await cb.message.edit_text(f"Сохранённые промпты (всего {total}):", reply_markup=prompts_keyboard(tokens=tokens, page=page, total=total))
        await cb.answer()
        return

    if action == "settings":
        srepo = SettingRepo(db)
        # show key defaults (env) if not set
        keys = [
            ("ADMIN_REVIEW_CHAT_ID", str(settings.admin_review_chat_id or "")),
            ("DESTINATION_CHANNEL", str(settings.destination_channel or "")),
            ("PUBLISH_EVERY_MINUTES", str(settings.publish_every_minutes)),
            ("PUBLISH_BATCH_SIZE", str(settings.publish_batch_size)),
            ("KIE_IMAGES_COUNT", str(settings.kie_images_count)),
            ("EXTERNAL_BOT_USERNAME", settings.external_bot_username),
            ("EXTERNAL_BUTTON_TEXT", settings.external_button_text),
            ("CAPTION_EMOJIS", settings.caption_emojis),
            ("KIE_REGEN_TEMPLATE", settings.kie_regen_template),
            ("REWRITE_TEMPLATE", settings.rewrite_template),
        ]
        out = []
        for k, default in keys:
            v = await srepo.get(k)
            out.append((k, v if v is not None else default))
        await cb.message.edit_text("Настройки (нажмите чтобы изменить):", reply_markup=settings_keyboard(out))
        await cb.answer()
        return

    if action == "queue":
        repo = DraftRepo(db)
        drafts = await repo.list_approved_unpublished(limit=10)
        if not drafts:
            await cb.message.edit_text("Очередь пуста.", reply_markup=back_to_menu_kb())
            await cb.answer()
            return
        lines = ["Очередь (первые 10):"]
        for d in drafts:
            lines.append(f"- Draft #{d.id} (approved)")
        await cb.message.edit_text("\n".join(lines), reply_markup=back_to_menu_kb())
        await cb.answer()
        return

    if action == "manual":
        await state.set_state(ManualPostStates.waiting_text)
        await cb.message.edit_text("Отправьте текст поста одним сообщением. Потом я сделаю OpenAI+KIE и поставлю в очередь.", reply_markup=back_to_menu_kb())
        await cb.answer()
        return

    await cb.answer("Неизвестно", show_alert=True)


@router.callback_query(F.data == "ui:add_channel")
async def add_channel_click(cb: CallbackQuery, db: AsyncSession, state: FSMContext):
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.set_state("add_channel_wait")
    await cb.message.edit_text("Отправьте @username канала-источника (пример: @mychannel).", reply_markup=back_to_menu_kb())
    await cb.answer()


@router.message(StateFilter("add_channel_wait"), F.text)
async def add_channel_text(message: Message, db: AsyncSession, state: FSMContext):
    uid = message.from_user.id if message.from_user else 0
    if not await _ensure_admin(db, uid):
        return
    username = message.text.strip()
    if not username.startswith("@"):
        await message.answer("Нужно указать @username. Попробуйте ещё раз.", reply_markup=back_to_menu_kb())
        return
    repo = ChannelRepo(db)
    await repo.add(username)
    await state.clear()
    await message.answer("✅ Канал добавлен.", reply_markup=main_menu_keyboard())


@router.callback_query(ChannelCb.filter())
async def channel_actions(cb: CallbackQuery, callback_data: ChannelCb, db: AsyncSession):
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    if callback_data.action == "del":
        repo = ChannelRepo(db)
        await repo.remove(callback_data.username)
        await cb.answer("Удалено")
        # refresh
        rows = await repo.list()
        total = len(rows)
        page = 0
        chans = [c.username for c in rows[:PAGE_SIZE]]
        await cb.message.edit_text(f"Каналы-источники (всего {total}).", reply_markup=channels_keyboard(channels=chans, page=page, total=total))
        return
    await cb.answer("Неизвестно", show_alert=True)


@router.callback_query(PromptCb.filter())
async def prompt_actions(cb: CallbackQuery, callback_data: PromptCb, db: AsyncSession):
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    repo = PromptTokenRepo(db)
    if callback_data.action == "open":
        prompt = await repo.get(callback_data.token)
        if not prompt:
            await cb.answer("Не найдено", show_alert=True)
            return
        await cb.message.edit_text(f"Токен: {callback_data.token}\n\nПромпт:\n{prompt}", reply_markup=back_to_menu_kb())
        await cb.answer()
        return
    if callback_data.action == "del":
        await repo.delete(callback_data.token)
        await cb.answer("Удалено")
        await cb.message.edit_text("Удалено. Вернитесь в меню.", reply_markup=back_to_menu_kb())
        return
    await cb.answer("Неизвестно", show_alert=True)


@router.callback_query(SettingsCb.filter())
async def settings_click(cb: CallbackQuery, callback_data: SettingsCb, db: AsyncSession, state: FSMContext):
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await state.update_data(setting_key=callback_data.key)
    await state.set_state("setting_wait_value")
    await cb.message.edit_text(f"Отправьте новое значение для {callback_data.key} одним сообщением.", reply_markup=back_to_menu_kb())
    await cb.answer()


@router.message(StateFilter("setting_wait_value"), F.text)
async def settings_value(message: Message, db: AsyncSession, state: FSMContext):
    uid = message.from_user.id if message.from_user else 0
    if not await _ensure_admin(db, uid):
        return
    data = await state.get_data()
    key = data.get("setting_key")
    if not key:
        await state.clear()
        return
    value = message.text.strip()
    srepo = SettingRepo(db)
    await srepo.set(str(key), value)
    await state.clear()
    await message.answer("✅ Сохранено. Для применения интервала публикации может потребоваться перезапуск сервиса.", reply_markup=main_menu_keyboard())


@router.message(ManualPostStates.waiting_text)
async def manual_post_text(message: Message, db: AsyncSession, state: FSMContext):
    uid = message.from_user.id if message.from_user else 0
    if not await _ensure_admin(db, uid):
        return
    text = (message.text or message.caption or "").strip()
    if not text:
        await message.answer("Пустой текст. Пришлите текст или фото с подписью.", reply_markup=back_to_menu_kb())
        return

    file_ids: list[str] = []
    if message.photo:
        file_ids.append(message.photo[-1].file_id)
    if message.document and (message.document.mime_type or "").startswith("image/"):
        file_ids.append(message.document.file_id)

    await state.update_data(manual_text=text, manual_file_ids=file_ids)
    await state.set_state(ManualPostStates.waiting_confirm)
    await message.answer(
        "Сохранить и поставить в очередь? (будет OpenAI+KIE)",
        reply_markup=manual_confirm_kb(),
    )


@router.callback_query(F.data == "ui:manual_confirm")
async def manual_confirm(cb: CallbackQuery, db: AsyncSession, state: FSMContext, bot: Bot):
    # answer ASAP to avoid callback timeout
    try:
        await cb.answer()
    except Exception:
        pass
    
    uid = cb.from_user.id if cb.from_user else 0
    if not await _ensure_admin(db, uid):
        await cb.answer("Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    text = (data.get("manual_text") or "").strip()
    file_ids: list[str] = data.get("manual_file_ids") or []
    if not text:
        await cb.answer("Нет текста", show_alert=True)
        return
    source_chat_id = cb.message.chat.id
    source_message_id = cb.message.message_id

    try:
        image_urls: list[str] = []
        for fid in file_ids:
            try:
                tg_file = await bot.get_file(fid)
                image_urls.append(f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{tg_file.file_path}")
            except Exception as e:
                logger.warning("Manual: failed to resolve file_id to URL: %s", e)

        draft_id = await ingest_and_build_draft(
            db=db,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            original_text=text,
            source_image_urls=image_urls or None,
        )

        await send_to_review(db=db, bot=bot, draft_id=draft_id)

        await state.clear()
        await cb.message.edit_text(
            f"✅ Отправлено на модерацию: Draft #{draft_id}",
            reply_markup=back_to_menu_kb(),
        )
    except Exception as e:
        logger.exception("Manual ingest failed: %s", e)
        await state.clear()
        try:
            await cb.message.edit_text(f"⚠️ Ошибка: {e}", reply_markup=back_to_menu_kb())
        except Exception:
            await cb.message.answer(f"⚠️ Ошибка: {e}", reply_markup=back_to_menu_kb())
