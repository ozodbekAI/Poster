from __future__ import annotations

from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from src.common.config import settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(url: str) -> None:
    # sqlite+aiosqlite:///./data/app.db -> ensure ./data exists
    if url.startswith("sqlite"):
        # very small parser: look for '///' and take remainder as path
        if "///" in url:
            path = url.split("///", 1)[1]
            if path.startswith("/"):  # absolute
                p = Path(path)
            else:
                p = Path(path)
            if p.suffix in (".db", ".sqlite", ".sqlite3"):
                p.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
