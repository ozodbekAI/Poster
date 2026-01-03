from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infra.db.models import Channel, Draft, PromptToken, Admin, Setting


class AdminRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> Sequence[Admin]:
        res = await self.session.execute(select(Admin).order_by(Admin.created_at.asc()))
        return res.scalars().all()

    async def is_admin(self, user_id: int) -> bool:
        res = await self.session.execute(select(Admin).where(Admin.user_id == user_id))
        return res.scalar_one_or_none() is not None

    async def add(self, user_id: int) -> None:
        if await self.is_admin(user_id):
            return
        self.session.add(Admin(user_id=user_id))
        await self.session.commit()

    async def remove(self, user_id: int) -> int:
        res = await self.session.execute(delete(Admin).where(Admin.user_id == user_id))
        await self.session.commit()
        return res.rowcount or 0


class SettingRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> Optional[str]:
        res = await self.session.execute(select(Setting).where(Setting.key == key))
        obj = res.scalar_one_or_none()
        return obj.value if obj else None

    async def set(self, key: str, value: str) -> None:
        res = await self.session.execute(select(Setting).where(Setting.key == key))
        obj = res.scalar_one_or_none()
        if obj:
            obj.value = value
        else:
            self.session.add(Setting(key=key, value=value))
        await self.session.commit()

    async def all(self) -> Sequence[Setting]:
        res = await self.session.execute(select(Setting).order_by(Setting.key.asc()))
        return res.scalars().all()



class ChannelRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> Sequence[Channel]:
        res = await self.session.execute(select(Channel).order_by(Channel.id.asc()))
        return res.scalars().all()

    async def add(self, username: str) -> Channel:
        username = username.strip().lstrip("@")
        obj = Channel(username=username)
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def remove(self, username: str) -> int:
        username = username.strip().lstrip("@")
        res = await self.session.execute(delete(Channel).where(Channel.username == username))
        await self.session.commit()
        return res.rowcount or 0


class DraftRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def by_source(self, source_chat_id: int, source_message_id: int) -> Optional[Draft]:
        res = await self.session.execute(
            select(Draft).where(Draft.source_chat_id == source_chat_id, Draft.source_message_id == source_message_id)
        )
        return res.scalar_one_or_none()

    async def create(
        self,
        *,
        source_chat_id: int,
        source_message_id: int,
        original_text: str,
        caption: str,
        image_prompt: str,
        image_paths: list[str],
    ) -> Draft:
        obj = Draft(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            original_text=original_text,
            caption=caption,
            image_prompt=image_prompt,
            image_paths_json=json.dumps(image_paths, ensure_ascii=False),
            status="pending_review",
        )
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def get(self, draft_id: int) -> Optional[Draft]:
        res = await self.session.execute(select(Draft).where(Draft.id == draft_id))
        return res.scalar_one_or_none()

    async def set_status(self, draft_id: int, status: str) -> None:
        values = {"status": status, "updated_at": datetime.utcnow()}
        if status == "approved":
            values["approved_at"] = datetime.utcnow()
        if status == "published":
            values["published_at"] = datetime.utcnow()
        await self.session.execute(update(Draft).where(Draft.id == draft_id).values(**values))
        await self.session.commit()

    async def set_review_message(self, draft_id: int, *, chat_id: int, message_id: int) -> None:
        await self.session.execute(
            update(Draft).where(Draft.id == draft_id).values(review_chat_id=chat_id, review_message_id=message_id)
        )
        await self.session.commit()

    async def update_content(
        self,
        draft_id: int,
        *,
        caption: str,
        image_prompt: str,
        image_paths: list[str],
    ) -> None:
        await self.session.execute(
            update(Draft)
            .where(Draft.id == draft_id)
            .values(
                caption=caption,
                image_prompt=image_prompt,
                image_paths_json=json.dumps(image_paths, ensure_ascii=False),
                updated_at=datetime.utcnow(),
            )
        )
        await self.session.commit()

    async def list_approved_unpublished(self, limit: int) -> Sequence[Draft]:
        res = await self.session.execute(
            select(Draft)
            .where(Draft.status == "approved", Draft.published_at.is_(None))
            .order_by(Draft.approved_at.asc().nulls_last(), Draft.id.asc())
            .limit(limit)
        )
        return res.scalars().all()


class PromptTokenRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def put(self, token: str, prompt: str) -> None:
        res = await self.session.execute(select(PromptToken).where(PromptToken.token == token))
        obj = res.scalar_one_or_none()
        if obj:
            obj.prompt = prompt
        else:
            self.session.add(PromptToken(token=token, prompt=prompt))
        await self.session.commit()

    async def get(self, token: str) -> Optional[str]:
        res = await self.session.execute(select(PromptToken).where(PromptToken.token == token))
        obj = res.scalar_one_or_none()
        return obj.prompt if obj else None

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(PromptToken))
        return int(res.scalar_one())

    async def list_page(self, *, offset: int, limit: int) -> Sequence[PromptToken]:
        res = await self.session.execute(
            select(PromptToken).order_by(PromptToken.created_at.desc()).offset(offset).limit(limit)
        )
        return res.scalars().all()

    async def delete(self, token: str) -> int:
        res = await self.session.execute(delete(PromptToken).where(PromptToken.token == token))
        await self.session.commit()
        return res.rowcount or 0
