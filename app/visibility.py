"""Кто чьи задачи видит: владелец/рук — все; партнёр — свой team_group."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.job_titles import can_view_all_employees, is_partner_title
from app.models import Employee, EmployeeAccess


async def can_see_grant_ids(session: AsyncSession, viewer_id: int) -> list[int]:
    rows = (
        await session.scalars(
            select(EmployeeAccess.subject_id).where(EmployeeAccess.viewer_id == viewer_id)
        )
    ).all()
    return [int(x) for x in rows]


async def visible_subject_ids(
    session: AsyncSession, viewer: Employee
) -> set[int] | None:
    """None = все. Иначе id сотрудников, чьи задачи видны зрителю."""
    if can_view_all_employees(role=viewer.role, job_title=viewer.job_title):
        return None
    granted = await can_see_grant_ids(session, viewer.id)
    ids: set[int] = {viewer.id, *granted}
    team = (viewer.team_group or "").strip()
    if is_partner_title(viewer.job_title) and team:
        teammates = (
            await session.scalars(
                select(Employee.id).where(
                    Employee.active.is_(True),
                    Employee.team_group == team,
                )
            )
        ).all()
        ids.update(int(x) for x in teammates)
    return ids


async def load_visible_employees(
    session: AsyncSession, viewer: Employee
) -> list[Employee]:
    people = list(
        (
            await session.scalars(
                select(Employee)
                .where(Employee.active.is_(True))
                .order_by(Employee.name)
            )
        ).all()
    )
    subject_ids = await visible_subject_ids(session, viewer)
    if subject_ids is None:
        return people
    return [e for e in people if e.id in subject_ids]


def can_view_person(
    viewer: Employee,
    subject: Employee,
    *,
    subject_ids: set[int] | None,
) -> bool:
    if subject_ids is None:
        return True
    return int(subject.id) in subject_ids
