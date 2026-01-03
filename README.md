# Reposter

A small Telegram pipeline that:

1. **Userbot (Pyrogram)** listens to configured source channels and forwards new posts to the admin bot.
2. **Admin bot (Aiogram)** ingests each forwarded post, regenerates **one** image via KIE, generates a new Russian caption (HTML) via OpenAI using the regenerated image, and sends a ready-to-publish draft to the review chat.
3. Reviewers approve/reject/regenerate. Approved drafts go to the publish queue and are posted to the destination channel by the admin bot.

## High-level flow

### 1) Capture (Userbot)
- Entry point: `python -m src.main_userbot`
- Main handler: `src/infra/userbot/watcher.py:on_channel_post`
- It checks allowed channels from DB and forwards each new post to the admin bot user (`INGEST_BOT_USERNAME`).

Important:
- The userbot account must **join the source channel(s)**.
- The same account should **start** the admin bot once (open chat and press Start), otherwise forwarding can fail.

### 2) Ingest (Admin bot)
- Entry point: `python -m src.main_admin_bot`
- Main handler: `src/infra/telegram/handlers/ingest.py:ingest_any`
- It extracts:
  - forward origin (`source_chat_id`, `source_message_id`)
  - text (`message.text` or `message.caption`, can be empty)
  - image URL(s) from Telegram Bot API file URLs

Then it runs:
- `src/usecases/ingest_and_build_draft.py:ingest_and_build_draft`
  - Build KIE prompt from `KIE_REGEN_TEMPLATE`
  - KIE generates **one** image (saved under `data/media/...`)
  - OpenAI generates a new caption in Russian **based on the generated image**
  - Draft is stored in DB and sent to review chat

### 3) Review & regenerate
- Review handler: `src/infra/telegram/handlers/review.py:on_review`
- Buttons:
  - Approve → draft status becomes `approved`
  - Reject → draft status becomes `rejected`
  - Regenerate → uses the **current review message photo** as a new reference and regenerates the image + caption

### 4) Publishing
- Scheduler: `src/infra/scheduler/runner.py` (started automatically by `main_admin_bot`)
- Use case: `src/usecases/publish_queue.py:publish_queue_tick`
- Publishes approved drafts to `DESTINATION_CHANNEL` respecting limits (`PUBLISH_*`).

## Settings you will edit from the admin panel

In the bot admin panel: **Panel → Settings** you can change:
- `KIE_REGEN_TEMPLATE` — how to regenerate a new image from a reference image.
- `REWRITE_TEMPLATE` — how to produce the final Telegram caption (HTML).

If these are not present in DB, values from `.env` are used.

## Notes / common errors

### “Bad Request: chat not found”
- Bot is not a member/admin of the target chat/channel, or the chat id/username is wrong.
- For supergroups, the id is typically `-100...`.

### Pyrogram: `sqlite3.OperationalError: database is locked`
- You are running **multiple userbot instances** with the same session file.
- Stop all instances and run only one.
- Recommended: set `TELEGRAM_SESSION_STRING` (then the session runs `in_memory=True` and avoids sqlite locking).

# Poster
