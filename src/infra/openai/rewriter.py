from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from src.common.config import settings
from src.common.templates import DEFAULT_REWRITE_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewriterResult:
    # Telegram-ready HTML caption
    caption: str
    # A user-facing prompt (stored under token for Promptika deeplink)
    promptika_prompt: str


class OpenAIRewriter:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=settings.openai_api_key)

    @staticmethod
    def _as_data_url(image_bytes: bytes, mime: str) -> str:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _format_user_template(template: str | None, original_text: str) -> str:
        """Format the *user-provided* template safely.

        Admins may store any plain text here (often without JSON instructions).
        We still support the {original_text} placeholder, but must not crash
        on stray braces.
        """
        tpl = (template or settings.rewrite_template or DEFAULT_REWRITE_TEMPLATE).strip()
        try:
            return tpl.format(original_text=original_text or "")
        except Exception:
            return tpl + "\n\nИсходный текст: " + (original_text or "")

    @staticmethod
    def _wrap_as_json_task(user_template: str, *, original_text: str) -> str:
        """Force a stable, parseable output contract regardless of template."""
        ctx = (original_text or "").strip()
        ctx_block = f"\n\nКонтекст исходного поста (для смысла, не цитируй дословно):\n{ctx}" if ctx else ""

        return (
            "Используй следующий шаблон и требования. "
            "Шаблон — это только форма текста, сам промпт и инструкции НЕ показывай.\n\n"
            "Шаблон/черновик (как должен выглядеть итоговый caption):\n"
            f"{user_template}\n\n"
            "Требования к результату:\n"
            "- Язык: русский.\n"
            "- Итоговый caption должен выглядеть как в шаблоне (символы/переносы/структура).\n"
            "- Не добавляй заголовки типа 'Пример', 'Шаблон', 'Инструкция'.\n"
            "- Не упоминай промпт/модели/OpenAI/KIE.\n"
            "- Длина caption: до 850 символов (важно для Telegram).\n\n"
            "Дополнительно сгенерируй promptika_prompt:\n"
            "- 1–2 коротких предложения, без HTML, без ссылок, без кавычек.\n"
            "- Должен описывать, как пользователю сгенерировать похожий кадр/стиль.\n\n"
            "Формат ответа: верни строго JSON без лишнего текста: "
            '{"caption_html":"...","promptika_prompt":"..."}'
            + ctx_block
        )

    async def caption_from_image(
        self,
        *,
        image_bytes: bytes,
        image_mime: str,
        original_text: str,
        template: str | None = None,
    ) -> RewriterResult:
        """Generate a Telegram HTML caption and a user prompt based on the image."""

        # Admin template may be plain text. We always wrap it to enforce JSON output.
        user_template = self._format_user_template(template, original_text)
        user_instructions = self._wrap_as_json_task(user_template, original_text=original_text)

        # The Responses API supports multimodal inputs.
        # We keep system instructions stable and allow admins to edit the user template.
        sys = (settings.openai_system_instructions or "").strip() or (
            "You write engaging Telegram post captions in Russian. "
            "Follow the user's template strictly and return valid JSON when asked."
        )

        payload = {
            "model": settings.openai_model,
            "input": [
                {"role": "system", "content": sys},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_instructions},
                        {
                            "type": "input_image",
                            "image_url": self._as_data_url(image_bytes, image_mime),
                        },
                    ],
                },
            ],
            # NOTE: Do NOT pass response_format here.
            # Some openai-python builds reject this argument for Responses.create().
            # We enforce JSON by instruction and parse resp.output_text.
        }

        # openai-python is sync. Run in thread via anyio if needed; here we keep it simple.
        # This repo already uses async elsewhere; for compatibility we call the blocking client
        # in a worker thread with asyncio.to_thread.
        import asyncio

        def _call() -> dict:
            resp = self.client.responses.create(**payload)
            text = (resp.output_text or "").strip()
            if not text:
                raise RuntimeError("OpenAI returned empty output")
            try:
                return json.loads(text)
            except Exception:
                # Sometimes the SDK returns JSON already; try to find JSON in the text.
                try:
                    start = text.index("{")
                    end = text.rindex("}") + 1
                    return json.loads(text[start:end])
                except Exception as e:
                    raise RuntimeError(f"Failed to parse JSON from OpenAI: {e}; raw={text[:500]}")

        data = await asyncio.to_thread(_call)

        caption_html = str(data.get("caption_html") or "").strip()
        promptika_prompt = str(data.get("promptika_prompt") or "").strip()

        if not caption_html or not promptika_prompt:
            raise RuntimeError(f"OpenAI response missing fields: {data}")

        return RewriterResult(caption=caption_html, promptika_prompt=promptika_prompt)

    async def rewrite_text_only(self, *, original_text: str) -> RewriterResult:
        """Fallback when image captioning is not possible (vision model not available)."""

        user_template = self._format_user_template(
            settings.rewrite_template or DEFAULT_REWRITE_TEMPLATE,
            original_text,
        )
        template = self._wrap_as_json_task(user_template, original_text=original_text)

        sys = (settings.openai_system_instructions or "").strip() or (
            "You write engaging Telegram post captions in Russian. "
            "Follow the user's template strictly and return valid JSON when asked."
        )

        import asyncio

        def _call() -> dict:
            resp = self.client.responses.create(
                model=settings.openai_model,
                input=[
                    {"role": "system", "content": sys},
                    {"role": "user", "content": template},
                ],
            )
            text = (resp.output_text or "").strip()
            try:
                return json.loads(text)
            except Exception:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    return json.loads(text[start : end + 1])
                raise

        data = await asyncio.to_thread(_call)
        return RewriterResult(
            caption=str(data.get("caption_html") or "").strip(),
            promptika_prompt=str(data.get("promptika_prompt") or "").strip(),
        )
