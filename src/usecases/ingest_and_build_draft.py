from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.config import settings
from src.common.templates import DEFAULT_KIE_REGEN_TEMPLATE, DEFAULT_REWRITE_TEMPLATE
from src.infra.db.repositories import DraftRepo, PromptTokenRepo, SettingRepo
from src.infra.kie.client import KIEInsufficientCreditsError, KieClient
from src.infra.openai.rewriter import OpenAIRewriter

logger = logging.getLogger(__name__)


async def _get_setting(db: AsyncSession, key: str, default: str) -> str:
    try:
        srepo = SettingRepo(db)
        v = await srepo.get(key)
        if v is not None and str(v).strip() != "":
            return str(v)
    except Exception:
        # DB settings are optional; fallback to env defaults.
        pass
    return default


def _format_template(template: str, *, original_text: str) -> str:
    try:
        return template.format(original_text=original_text or "")
    except Exception:
        return template + "\n\nИсходный текст: " + (original_text or "")


async def ingest_and_build_draft(
    *,
    db: AsyncSession,
    source_chat_id: int,
    source_message_id: int,
    original_text: str,
    source_image_urls: list[str] | None = None,
) -> int:
    """Create Draft from a forwarded channel post.

    Pipeline:
    1) Build KIE prompt (reference-image regeneration) using KIE_REGEN_TEMPLATE.
    2) KIE generates ONE image (saved on disk).
    3) OpenAI generates Telegram HTML caption based on the generated image, using REWRITE_TEMPLATE.
    4) Save draft, store Promptika prompt under token.
    """

    draft_repo = DraftRepo(db)
    existing = await draft_repo.by_source(source_chat_id, source_message_id)
    if existing:
        return existing.id

    original_text = (original_text or "").strip()
    logger.info(
        "Ingest: start chat=%s msg=%s images=%s text_len=%s",
        source_chat_id,
        source_message_id,
        len(source_image_urls or []),
        len(original_text),
    )

    # 1) KIE prompt
    kie_template = await _get_setting(
        db,
        "KIE_REGEN_TEMPLATE",
        settings.kie_regen_template or DEFAULT_KIE_REGEN_TEMPLATE,
    )
    kie_prompt = _format_template(kie_template, original_text=original_text)

    # 2) KIE generate (single image)
    image_paths: list[str] = []
    kie = KieClient()
    try:
        out_dir = Path("data/media") / f"draft_{source_chat_id}_{source_message_id}"
        logger.info(
            "Ingest: KIE generate start draft_key=%s_%s model=%s ref_images=%s",
            source_chat_id,
            source_message_id,
            settings.kie_model,
            len(source_image_urls or []),
        )
        image_paths = await kie.generate(
            prompt=kie_prompt,
            out_dir=str(out_dir),
            n=1,
            image_urls=source_image_urls,
            output_format=settings.kie_output_format,
            image_size=settings.kie_image_size,
        )
        image_paths = (image_paths or [])[:1]
        logger.info("Ingest: KIE generate done images=%s", len(image_paths))
    except KIEInsufficientCreditsError as e:
        logger.error("KIE credits insufficient: %s", e)
        image_paths = []
    except Exception as e:
        logger.exception("KIE generate failed: %s", e)
        image_paths = []
    finally:
        try:
            await kie.close()
        except Exception:
            pass

    # 3) OpenAI caption (based on generated image)
    caption_html = ""
    promptika_prompt = ""
    rewriter = OpenAIRewriter()

    if image_paths:
        try:
            rewrite_template = await _get_setting(
                db,
                "REWRITE_TEMPLATE",
                settings.rewrite_template or DEFAULT_REWRITE_TEMPLATE,
            )
            img_path = image_paths[0]
            img_bytes = Path(img_path).read_bytes()
            # Guess mime by extension (Telegram photos are usually jpg/png)
            suf = Path(img_path).suffix.lower()
            mime = "image/png" if suf == ".png" else "image/jpeg"
            rr = await rewriter.caption_from_image(
                image_bytes=img_bytes,
                image_mime=mime,
                original_text=original_text,
                template=rewrite_template,
            )
            caption_html = rr.caption
            promptika_prompt = rr.promptika_prompt
            logger.info("Ingest: OpenAI caption done")
        except Exception as e:
            logger.exception("OpenAI caption-from-image failed: %s", e)

    # Fallback: if caption still empty
    if not caption_html or not promptika_prompt:
        try:
            rr = await rewriter.rewrite_text_only(original_text=original_text)
            caption_html = rr.caption
            promptika_prompt = rr.promptika_prompt
            logger.info("Ingest: OpenAI text-only fallback done")
        except Exception as e:
            logger.exception("OpenAI text-only fallback failed: %s", e)
            # absolute fallback
            caption_html = (original_text or "").strip() or "(без текста)"
            promptika_prompt = (original_text or "").strip() or ""

    # 4) Persist
    d = await draft_repo.create(
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        original_text=original_text,
        caption=caption_html,
        image_prompt=promptika_prompt,
        image_paths=image_paths,
    )

    token = f"p_{d.id}"
    token_repo = PromptTokenRepo(db)
    await token_repo.put(token, promptika_prompt)

    logger.info("Ingest: draft created id=%s token=%s", d.id, token)
    return d.id
