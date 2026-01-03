from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

from src.common.templates import DEFAULT_KIE_REGEN_TEMPLATE, DEFAULT_REWRITE_TEMPLATE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    admin_ids_csv: str | None = Field(default=None, alias="ADMIN_IDS")
    admin_review_chat_id: int | None = Field(default=None, alias="ADMIN_REVIEW_CHAT_ID")
    destination_channel: str | None = Field(default=None, alias="DESTINATION_CHANNEL")

    userbot_sender_id: int | None = Field(default=None, alias="USERBOT_SENDER_ID")
    ingest_bot_username: str | None = Field(default=None, alias="INGEST_BOT_USERNAME")

    telegram_api_id: int | None = Field(default=None, alias="TELEGRAM_API_ID")
    telegram_api_hash: str | None = Field(default=None, alias="TELEGRAM_API_HASH")
    telegram_session_file: str = Field(default="pyrogram", alias="TELEGRAM_SESSION_FILE")
    telegram_session_string: str | None = Field(default=None, alias="TELEGRAM_SESSION_STRING")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_system_instructions: str = Field(default="You are a helpful editor.", alias="OPENAI_SYSTEM_INSTRUCTIONS")
    # Caption template. If omitted, DEFAULT_REWRITE_TEMPLATE is used.
    rewrite_template: str = Field(default=DEFAULT_REWRITE_TEMPLATE, alias="REWRITE_TEMPLATE")

    # KIE prompt template for reference-image regeneration.
    # Placeholders: {original_text}
    kie_regen_template: str = Field(default=DEFAULT_KIE_REGEN_TEMPLATE, alias="KIE_REGEN_TEMPLATE")

    kie_base_url: str | None = Field(default=None, alias="KIE_BASE_URL")
    kie_api_url: str | None = Field(default=None, alias="KIE_API_URL")
    kie_api_base: str | None = Field(default=None, alias="KIE_API_BASE")
    kie_create_path: str = Field(default="/jobs/createTask", alias="KIE_CREATE_PATH")
    kie_query_path: str = Field(default="/jobs/recordInfo", alias="KIE_QUERY_PATH")
    kie_model: str = Field(default="google/nano-banana-edit", alias="KIE_MODEL")
    kie_output_format: str = Field(default="png", alias="KIE_OUTPUT_FORMAT")
    kie_image_size: str = Field(default="3:4", alias="KIE_IMAGE_SIZE")
    kie_poll_interval_sec: int = Field(default=10, alias="KIE_POLL_INTERVAL_SEC")
    kie_max_attempts: int = Field(default=120, alias="KIE_MAX_ATTEMPTS")
    kie_api_key: str | None = Field(default=None, alias="KIE_API_KEY")
    kie_generate_path: str = Field(default="/generate", alias="KIE_GENERATE_PATH")
    kie_images_count: int = Field(default=2, alias="KIE_IMAGES_COUNT")

    caption_emojis: str = Field(default="✨🔥✅", alias="CAPTION_EMOJIS")

    publish_every_minutes: int = Field(default=30, alias="PUBLISH_EVERY_MINUTES")
    publish_batch_size: int = Field(default=1, alias="PUBLISH_BATCH_SIZE")

    external_bot_username: str = Field(default="PromptikaBot", alias="EXTERNAL_BOT_USERNAME")
    external_button_text: str = Field(default="Попробовать", alias="EXTERNAL_BUTTON_TEXT")

    resolver_api_key: str | None = Field(default=None, alias="RESOLVER_API_KEY")
    resolver_bind: str = Field(default="0.0.0.0", alias="RESOLVER_BIND")
    resolver_port: int = Field(default=8080, alias="RESOLVER_PORT")

    database_url: str = Field(default="sqlite+aiosqlite:///./data/app.db", alias="DATABASE_URL")

    tz: str = Field(default="Asia/Tashkent", alias="TZ")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


settings = Settings()

def admin_ids() -> list[int]:
    if not settings.admin_ids_csv:
        return []
    ids = []
    for part in settings.admin_ids_csv.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                continue
    return ids