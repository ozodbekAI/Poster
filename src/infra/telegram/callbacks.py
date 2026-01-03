from __future__ import annotations
from aiogram.filters.callback_data import CallbackData

class DraftCb(CallbackData, prefix="draft"):
    action: str
    draft_id: int

class PanelCb(CallbackData, prefix="panel"):
    action: str  
    page: int = 0

class ChannelCb(CallbackData, prefix="chan"):
    action: str  
    username: str

class PromptCb(CallbackData, prefix="pt"):
    action: str  
    token: str

class SettingsCb(CallbackData, prefix="set"):
    action: str  
    key: str
