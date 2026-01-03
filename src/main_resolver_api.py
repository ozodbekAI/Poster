from __future__ import annotations

import logging
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from src.common.logging import setup_logging
from src.common.config import settings
from src.infra.db.init_db import init_db
from src.infra.db.base import async_session_maker
from src.infra.db.repositories import PromptTokenRepo

logger = logging.getLogger(__name__)
app = FastAPI(title="Prompt Resolver API", version="1.0.0")

class ResolveResponse(BaseModel):
    token: str
    prompt: str

@app.on_event("startup")
async def _startup():
    setup_logging()
    await init_db()
    logger.info("Resolver API started")

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/v1/prompt/{token}", response_model=ResolveResponse)
async def resolve_prompt(
    token: str,
    consume: bool = Query(default=False),
    x_resolver_key: str | None = Header(default=None, alias="X-Resolver-Key"),
):
    if settings.resolver_api_key:
        if not x_resolver_key or x_resolver_key != settings.resolver_api_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

    async with async_session_maker() as db:
        repo = PromptTokenRepo(db)
        prompt = await repo.get(token)
        if not prompt:
            raise HTTPException(status_code=404, detail="Token not found")
        if consume:
            await repo.delete(token)
        return ResolveResponse(token=token, prompt=prompt)
