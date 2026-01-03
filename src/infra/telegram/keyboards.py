from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.infra.telegram.callbacks import DraftCb

def review_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Одобрить", callback_data=DraftCb(action="approve", draft_id=draft_id).pack())
    kb.button(text="❌ Отклонить", callback_data=DraftCb(action="reject", draft_id=draft_id).pack())
    # Open regen menu (img/caption/all)
    kb.button(text="🔁 Реген", callback_data=DraftCb(action="regen_menu", draft_id=draft_id).pack())
    kb.adjust(3)
    return kb.as_markup()

def regen_keyboard(draft_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🖼 Только картинки", callback_data=DraftCb(action="regen_img", draft_id=draft_id).pack())
    kb.button(text="📝 Только caption", callback_data=DraftCb(action="regen_cap", draft_id=draft_id).pack())
    kb.button(text="🧩 Всё заново", callback_data=DraftCb(action="regen_all", draft_id=draft_id).pack())
    kb.adjust(1)
    return kb.as_markup()

def url_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])

from src.infra.telegram.callbacks import PanelCb, ChannelCb, PromptCb, SettingsCb

PAGE_SIZE = 6

def main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить пост вручную", callback_data=PanelCb(action="manual", page=0))
    kb.button(text="🗂 Сохранённые промпты", callback_data=PanelCb(action="prompts", page=0))
    kb.button(text="📡 Каналы", callback_data=PanelCb(action="channels", page=0))
    kb.button(text="⚙️ Настройки", callback_data=PanelCb(action="settings", page=0))
    kb.button(text="📤 Очередь", callback_data=PanelCb(action="queue", page=0))
    kb.adjust(1)
    return kb.as_markup()

def back_to_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 В меню", callback_data=PanelCb(action="menu", page=0))
    return kb.as_markup()

def pagination_row(action: str, page: int, has_prev: bool, has_next: bool) -> list[InlineKeyboardButton]:
    row = []
    if has_prev:
        row.append(InlineKeyboardButton(text="⬅️", callback_data=PanelCb(action=action, page=page-1).pack()))
    if has_next:
        row.append(InlineKeyboardButton(text="➡️", callback_data=PanelCb(action=action, page=page+1).pack()))
    return row

def channels_keyboard(*, channels: list[str], page: int, total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить канал", callback_data="ui:add_channel")
    for u in channels:
        kb.button(text=f"🗑 @{u}", callback_data=ChannelCb(action="del", username=u))
    # pagination
    has_prev = page > 0
    has_next = (page+1)*PAGE_SIZE < total
    if has_prev or has_next:
        kb.row(*pagination_row("channels", page, has_prev, has_next))
    kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data=PanelCb(action="menu", page=0).pack()))
    kb.adjust(1)
    return kb.as_markup()

def prompts_keyboard(*, tokens: list[str], page: int, total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tokens:
        kb.row(
            InlineKeyboardButton(text=f"📄 {t}", callback_data=PromptCb(action="open", token=t).pack()),
            InlineKeyboardButton(text="🗑", callback_data=PromptCb(action="del", token=t).pack()),
        )
    has_prev = page > 0
    has_next = (page+1)*PAGE_SIZE < total
    if has_prev or has_next:
        kb.row(*pagination_row("prompts", page, has_prev, has_next))
    kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data=PanelCb(action="menu", page=0).pack()))
    return kb.as_markup()

def settings_keyboard(items: list[tuple[str,str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, value in items:
        kb.row(
            InlineKeyboardButton(text=f"{key}: {value}", callback_data=SettingsCb(action="edit", key=key).pack())
        )
    kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data=PanelCb(action="menu", page=0).pack()))
    return kb.as_markup()

def manual_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ В очередь", callback_data="ui:manual_confirm")
    kb.button(text="❌ Отмена", callback_data=PanelCb(action="menu", page=0))
    kb.adjust(2)
    return kb.as_markup()
