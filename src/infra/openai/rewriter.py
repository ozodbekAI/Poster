from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

import httpx
from openai import OpenAI

from src.common.config import settings
from src.common.templates import DEFAULT_REWRITE_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewriterResult:
    caption: str
    promptika_prompt: str


class OpenAIRewriter:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        # --- PROXY CONFIG (host:port:user:pass) ---
        proxy_raw = "156.233.82.121:63464:11f1wsnM:mddvZFkM"
        host, port, user, password = proxy_raw.split(":", 3)

        # HTTP proxy URL with basic auth
        proxy_url = f"http://{user}:{password}@{host}:{port}"

        # httpx client with proxy (applies to both http and https)
        http_client = httpx.Client(
            proxies={
                "http://": proxy_url,
                "https://": proxy_url,
            },
            timeout=httpx.Timeout(60.0, connect=30.0),
            # verify=True  # default; leave as-is unless your proxy uses MITM cert issues
        )

        # Pass custom http client into OpenAI
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            http_client=http_client,
        )

    @staticmethod
    def _as_data_url(image_bytes: bytes, mime: str) -> str:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _format_user_template(template: str | None, original_text: str) -> str:
        tpl = (template or settings.rewrite_template or DEFAULT_REWRITE_TEMPLATE).strip()
        try:
            return tpl.format(original_text=original_text or "")
        except Exception:
            return tpl + "\n\nИсходный текст: " + (original_text or "")

    @staticmethod
    def _wrap_as_json_task(user_template: str, *, original_text: str) -> str:
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
            "- Длина caption: до 200 символов (важно для Telegram).\n\n"
            "Дополнительно сгенерируй promptika_prompt:\n"
            "- 1–2 коротких предложения, без HTML, без ссылок, без кавычек.\n"
            "- Должен описывать, как пользователю сгенерировать похожий кадр/стиль.\n\n"
            'Формат ответа: верни строго JSON без лишнего текста: {"caption_html":"...","promptika_prompt":"..."}'
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
        user_template = self._format_user_template(template, original_text)
        user_instructions = self._wrap_as_json_task(user_template, original_text=original_text)

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
                        {"type": "input_image", "image_url": self._as_data_url(image_bytes, image_mime)},
                    ],
                },
            ],
        }

        import asyncio

        def _call() -> dict:
            resp = self.client.responses.create(**payload)
            text = (resp.output_text or "").strip()
            if not text:
                raise RuntimeError("OpenAI returned empty output")

            try:
                return json.loads(text)
            except Exception:
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
