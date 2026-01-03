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
    """Read a setting from DB with a safe fallback to env defaults."""
    try:
        v = await SettingRepo(db).get(key)
        if v is not None and str(v).strip() != "":
            return str(v)
    except Exception:
        pass
    return default


def _format_template(template: str, *, original_text: str) -> str:
    """Safely format templates that may include braces."""
    try:
        return template.format(original_text=original_text or "")
    except Exception:
        return template + "\n\nИсходный текст: " + (original_text or "")


async def regenerate_draft(
    *,
    db: AsyncSession,
    draft_id: int,
    mode: str = "regen_all",
    reference_image_urls: list[str] | None = None,
) -> bool:
    """Regenerate draft content.

    mode:
      - regen_img: regenerate ONLY images (keep caption & prompt)
      - regen_cap: regenerate ONLY caption/prompt (keep images)
      - regen_all: regenerate both images and caption/prompt

    Returns True if something was updated.
    """

    mode = (mode or "regen_all").strip()
    if mode not in {"regen_img", "regen_cap", "regen_all"}:
        mode = "regen_all"

    drepo = DraftRepo(db)
    d = await drepo.get(draft_id)
    if not d:
        return False

    original_text = (d.original_text or "").strip()
    updated = False

    # -----------------------------
    # 1) (Optional) KIE image regen
    # -----------------------------
    image_paths: list[str] = d.image_paths
    if mode in {"regen_img", "regen_all"}:
        kie_template = await _get_setting(
            db,
            "KIE_REGEN_TEMPLATE",
            settings.kie_regen_template or DEFAULT_KIE_REGEN_TEMPLATE,
        )
        kie_prompt = _format_template(kie_template, original_text=original_text)

        kie = KieClient()
        try:
            out_dir = Path("data/media") / f"draft_{d.source_chat_id}_{d.source_message_id}_regen"
            logger.info(
                "Regen: KIE start draft_id=%s mode=%s ref_images=%s model=%s",
                draft_id,
                mode,
                len(reference_image_urls or []),
                settings.kie_model,
            )
            new_paths = await kie.generate(
                prompt=kie_prompt,
                out_dir=str(out_dir),
                n=1,
                image_urls=reference_image_urls,
                output_format=settings.kie_output_format,
                image_size=settings.kie_image_size,
            )
            new_paths = (new_paths or [])[:1]
            if new_paths:
                image_paths = new_paths
                updated = True
            logger.info("Regen: KIE done draft_id=%s images=%s", draft_id, len(new_paths or []))
        except KIEInsufficientCreditsError as e:
            logger.error("Regen: KIE credits insufficient draft_id=%s err=%s", draft_id, e)
        except Exception as e:
            logger.exception("Regen: KIE failed draft_id=%s err=%s", draft_id, e)
        finally:
            try:
                await kie.close()
            except Exception:
                pass

        # If we requested image regeneration but it failed, do not touch draft.
        if mode in {"regen_img", "regen_all"} and not updated and mode != "regen_cap":
            return False

    # ---------------------------------
    # 2) (Optional) OpenAI caption regen
    # ---------------------------------
    caption = d.caption
    promptika_prompt = d.image_prompt
    if mode in {"regen_cap", "regen_all"}:
        rewriter = OpenAIRewriter()
        rewrite_template = await _get_setting(
            db,
            "REWRITE_TEMPLATE",
            settings.rewrite_template or DEFAULT_REWRITE_TEMPLATE,
        )

        try:
            if image_paths:
                img_path = Path(image_paths[0])
                img_bytes = img_path.read_bytes()
                suf = img_path.suffix.lower()
                mime = "image/png" if suf == ".png" else "image/jpeg"
                rr = await rewriter.caption_from_image(
                    image_bytes=img_bytes,
                    image_mime=mime,
                    original_text=original_text,
                    template=rewrite_template,
                )
            else:
                rr = await rewriter.rewrite_text_only(original_text=original_text)

            caption = rr.caption
            promptika_prompt = rr.promptika_prompt
            updated = True
            logger.info("Regen: OpenAI caption done draft_id=%s", draft_id)
        except Exception as e:
            logger.exception("Regen: OpenAI caption failed draft_id=%s err=%s", draft_id, e)

    # -----------------------------
    # 3) Persist only if something changed
    # -----------------------------
    if not updated:
        return False

    # If only images were regenerated, keep caption/prompt.
    if mode == "regen_img":
        caption = d.caption
        promptika_prompt = d.image_prompt

    await drepo.update_content(
        draft_id,
        caption=caption,
        image_prompt=promptika_prompt,
        image_paths=image_paths,
    )

    token = f"p_{draft_id}"
    try:
        await PromptTokenRepo(db).put(token, promptika_prompt)
    except Exception:
        # token storage is not critical for regeneration
        logger.exception("Regen: failed to update prompt token draft_id=%s", draft_id)

    logger.info("Regen: done draft_id=%s mode=%s", draft_id, mode)
    return True
