from __future__ import annotations

import html as _html
import re as _re
from typing import Iterable, List, Tuple, Optional


# Telegram (Bot API) limits are defined in "UTF-16 code units" for many entity-related constraints.
# Using UTF-16 length is the safest way to avoid "caption too long" with emoji / surrogate pairs.
def tg_utf16_len(text: str) -> int:
    t = text or ""
    return len(t.encode("utf-16-le")) // 2


def tg_utf16_clip(text: str, limit: int, *, ellipsis: str = "…") -> str:
    t = (text or "").strip()
    if limit <= 0:
        return ""
    if tg_utf16_len(t) <= limit:
        return t

    # Keep room for ellipsis
    target = max(0, limit - tg_utf16_len(ellipsis))
    if target <= 0:
        return ellipsis[:limit]

    # Binary search over code points; UTF-16 length is monotonic w.r.t prefix.
    lo, hi = 0, len(t)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if tg_utf16_len(t[:mid]) <= target:
            lo = mid
        else:
            hi = mid - 1

    return t[:lo].rstrip() + ellipsis


_TAG_RE = _re.compile(r"<[^>]*>")
_WS_RE = _re.compile(r"[ \t\f\v]+")


def strip_html(text: str) -> str:
    """Best-effort HTML tag stripper for Telegram captions.

    This is intentionally simple: it removes tags and unescapes HTML entities.
    """
    t = (text or "").strip()
    t = _TAG_RE.sub("", t)
    t = _html.unescape(t)
    # Normalize whitespace a bit
    t = _WS_RE.sub(" ", t)
    return t.strip()


def prepare_photo_caption(
    caption_html: str,
    *,
    caption_limit: int = 1024,
) -> tuple[str, Optional[str], Optional[str]]:
    """Return (caption_for_photo, overflow_text_or_none, parse_mode_or_none).

    Strategy:
    - If the caption fits, keep it as-is and mark parse_mode='HTML' (since we generate Telegram HTML).
    - If it does NOT fit, switch to plain text (strip HTML) for safety and clip it.
      Also return the full plain text as overflow (caller may send as follow-up messages).
    """
    raw = (caption_html or "").strip()
    if tg_utf16_len(raw) <= caption_limit:
        return raw, None, "HTML"

    plain = strip_html(raw)
    head = tg_utf16_clip(plain, caption_limit)
    return head, plain, None


def chunk_text(text: str, *, limit: int = 4096) -> List[str]:
    """Split long text into Telegram-safe chunks by UTF-16 length."""
    t = (text or "").strip()
    if not t:
        return []

    chunks: List[str] = []
    while t:
        if tg_utf16_len(t) <= limit:
            chunks.append(t)
            break

        # Try to split on a paragraph boundary first.
        cut = None
        # Find last \n\n within limit
        # Walk back a bit for performance
        window = t[: min(len(t), 5000)]
        # We'll binary search the cut point in code points.
        lo, hi = 0, len(t)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if tg_utf16_len(t[:mid]) <= limit:
                lo = mid
            else:
                hi = mid - 1
        # lo is max prefix within limit
        prefix = t[:lo]

        # Prefer splitting on last double newline or single newline.
        split_at = prefix.rfind("\n\n")
        if split_at != -1 and split_at > 0:
            cut = split_at + 2
        else:
            split_at = prefix.rfind("\n")
            if split_at != -1 and split_at > 0:
                cut = split_at + 1
            else:
                # Fall back to a hard cut.
                cut = lo

        part = t[:cut].strip()
        if part:
            chunks.append(part)
        t = t[cut:].strip()

    return chunks
