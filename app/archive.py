"""Архивация выполненных задач через 7 дней — по месяцам completed_at."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import Task, TaskAssignee
from app.tasks_service import add_event

logger = logging.getLogger("archive")

ARCHIVE_AFTER_DAYS = 7


async def archive_old_done_tasks(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=ARCHIVE_AFTER_DAYS)
    async with session_factory() as session:
        tasks = (
            await session.scalars(
                select(Task).where(
                    Task.active.is_(True),
                    Task.status == "done",
                    Task.archived_at.is_(None),
                    Task.completed_at.is_not(None),
                    Task.completed_at <= cutoff,
                )
            )
        ).all()
        now = datetime.utcnow()
        for t in tasks:
            t.archived_at = now
            await add_event(
                session,
                t.id,
                "Отправлена в архив (выполнена более 7 дней назад)",
                kind="archived",
            )
        await session.commit()
        n = len(tasks)
        if n:
            logger.info("archived %s done tasks", n)
        return {"ok": True, "archived": n}


async def list_archive_months(session: AsyncSession) -> list[dict]:
    """Месяцы архива по дате выполнения."""
    rows = (
        await session.execute(
            select(
                extract("year", Task.completed_at).label("year"),
                extract("month", Task.completed_at).label("month"),
                func.count(Task.id).label("count"),
            )
            .where(
                Task.active.is_(True),
                Task.archived_at.is_not(None),
                Task.completed_at.is_not(None),
            )
            .group_by("year", "month")
            .order_by(extract("year", Task.completed_at).desc(), extract("month", Task.completed_at).desc())
        )
    ).all()
    out = []
    for year, month, count in rows:
        out.append({"year": int(year), "month": int(month), "count": int(count)})
    return out


async def list_archive_tasks(
    session: AsyncSession, *, year: int, month: int
) -> list[Task]:
    return list(
        (
            await session.scalars(
                select(Task)
                .where(
                    Task.active.is_(True),
                    Task.archived_at.is_not(None),
                    Task.completed_at.is_not(None),
                    extract("year", Task.completed_at) == year,
                    extract("month", Task.completed_at) == month,
                )
                .options(
                    selectinload(Task.assignee),
                    selectinload(Task.project),
                    selectinload(Task.created_by),
                    selectinload(Task.completed_by),
                    selectinload(Task.assignees).selectinload(TaskAssignee.employee),
                )
                .order_by(Task.completed_at.desc(), Task.id.desc())
            )
        ).all()
    )
