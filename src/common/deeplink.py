from __future__ import annotations
from urllib.parse import quote

def make_external_bot_url(bot_username: str, token: str) -> str:
    return f"https://t.me/{bot_username}?start={quote(token)}"
