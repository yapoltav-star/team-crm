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
        for stmt in (
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS articles VARCHAR(500) DEFAULT ''",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_by_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS due_date DATE",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal'",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP",
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS template_id INTEGER",
            "ALTER TABLE employees ALTER COLUMN telegram_id TYPE BIGINT",
        ):
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass

    from app.catalog import seed_articles_from_file

    async with SessionLocal() as session:
        await seed_articles_from_file(session)
        # migrate legacy single assignee → task_assignees
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO task_assignees (task_id, employee_id)
                    SELECT id, assignee_id FROM tasks
                    WHERE assignee_id IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM task_assignees ta
                        WHERE ta.task_id = tasks.id AND ta.employee_id = tasks.assignee_id
                      )
                    """
                )
            )
            await session.commit()
        except Exception:
            await session.rollback()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
