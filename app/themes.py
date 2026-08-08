from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskTheme

DEFAULT_SYSTEM_THEMES = [
    ("product", "работа с товаром"),
    ("team", "работа с командой"),
    ("personal", "личные дела"),
    ("finance", "финансы"),
    ("stock", "остатки"),
]


async def ensure_system_themes(session: AsyncSession) -> None:
    existing = {
        str(k)
        for k in (
            await session.scalars(
                select(TaskTheme.key).where(TaskTheme.is_system.is_(True))
            )
        ).all()
        if k
    }
    changed = False
    for i, (key, title) in enumerate(DEFAULT_SYSTEM_THEMES):
        if key in existing:
            continue
        session.add(
            TaskTheme(
                key=key,
                title=title,
                is_system=True,
                owner_employee_id=None,
                position=i,
                active=True,
            )
        )
        changed = True
    if changed:
        await session.commit()


async def themes_for_employee(
    session: AsyncSession, employee_id: int | None, *, include_inactive: bool = False
) -> list[TaskTheme]:
    """Системные темы + личные темы сотрудника."""
    q = select(TaskTheme)
    if not include_inactive:
        q = q.where(TaskTheme.active.is_(True))
    if employee_id is None:
        q = q.where(TaskTheme.is_system.is_(True))
    else:
        q = q.where(
            or_(
                TaskTheme.is_system.is_(True),
                TaskTheme.owner_employee_id == employee_id,
            )
        )
    q = q.order_by(
        TaskTheme.is_system.desc(),
        TaskTheme.position.asc(),
        TaskTheme.id.asc(),
    )
    return list((await session.scalars(q)).all())
