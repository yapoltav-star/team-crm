from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

_settings = get_settings()
if _settings.sqlalchemy_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)

engine = create_async_engine(_settings.sqlalchemy_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # мягкая миграция для уже существующей БД на Railway
        for stmt in (
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS articles VARCHAR(500) DEFAULT ''",
            "ALTER TABLE employees ALTER COLUMN telegram_id TYPE BIGINT",
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
