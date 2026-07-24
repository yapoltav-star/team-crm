from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Employee, Task, TaskAssignee, TaskComment, TaskEvent, TaskTemplate

STATUS_LABEL = {"todo": "Новая", "doing": "В работе", "done": "Выполнено"}

_DEFAULT_DUE_DAYS = 3


def resolve_due_date(
    today: date,
    *,
    text: str = "",
    explicit: date | None = None,
    hint: str | None = None,
) -> date:
    """Срок: явный → сегодня/завтра из текста/hint → иначе +3 дня."""
    if explicit is not None:
        return explicit
    h = (hint or "").strip().lower()
    blob = f"{h} {text}".lower()
    if h in {"today", "сегодня"} or re.search(
        r"(?i)(?<![а-яa-z])(сегодня|на\s+сегодня|today)(?![а-яa-z])", blob
    ):
        return today
    if h in {"tomorrow", "завтра"} or re.search(
        r"(?i)(?<![а-яa-z])(завтра|на\s+завтра|tomorrow)(?![а-яa-z])", blob
    ):
        return today + timedelta(days=1)
    if h in {"day_after", "послезавтра"} or re.search(
        r"(?i)(?<![а-яa-z])послезавтра(?![а-яa-z])", blob
    ):
        return today + timedelta(days=2)
    return today + timedelta(days=_DEFAULT_DUE_DAYS)


async def add_event(
    session: AsyncSession,
    task_id: int,
    message: str,
    *,
    kind: str,
    actor_id: int | None = None,
) -> None:
    session.add(
        TaskEvent(
            task_id=task_id,
            actor_id=actor_id,
            kind=kind,
            message=message[:500],
            created_at=datetime.utcnow(),
        )
    )


async def set_assignees(
    session: AsyncSession,
    task: Task,
    employee_ids: list[int],
    *,
    actor_id: int | None = None,
    log: bool = True,
) -> None:
    ids = []
    seen: set[int] = set()
    for i in employee_ids:
        if i and i not in seen:
            seen.add(i)
            ids.append(i)
    # без lazy-load (async → MissingGreenlet)
    await session.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    await session.flush()
    for eid in ids:
        session.add(TaskAssignee(task_id=task.id, employee_id=eid))
    task.assignee_id = ids[0] if ids else None
    # сбросить кэш relationship, если был
    session.expire(task, ["assignees"])
    if log and ids:
        people = (
            await session.scalars(select(Employee).where(Employee.id.in_(ids)))
        ).all()
        names = ", ".join(p.name for p in people)
        await add_event(
            session,
            task.id,
            f"Назначены: {names}",
            kind="assigned",
            actor_id=actor_id,
        )


async def apply_status(
    session: AsyncSession,
    task: Task,
    new_status: str,
    *,
    actor_id: int | None = None,
) -> None:
    if new_status not in STATUS_LABEL:
        raise ValueError("bad status")
    old = task.status
    if old == new_status:
        return
    now = datetime.utcnow()
    task.status = new_status
    if new_status == "doing" and not task.started_at:
        task.started_at = now
    if new_status == "done":
        task.completed_at = now
        task.completed_by_id = actor_id
    if new_status != "done":
        # reopen
        if old == "done":
            task.completed_at = None
            task.completed_by_id = None
    await add_event(
        session,
        task.id,
        f"Статус: {STATUS_LABEL.get(old, old)} → {STATUS_LABEL[new_status]}",
        kind="status",
        actor_id=actor_id,
    )


def due_flag(due: date | None, status: str, today: date) -> str | None:
    if status == "done" or not due:
        return "done" if status == "done" else None
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    return None


async def load_task_full(session: AsyncSession, task_id: int) -> Task:
    return (
        await session.scalars(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.project),
                selectinload(Task.created_by),
                selectinload(Task.completed_by),
                selectinload(Task.assignees).selectinload(TaskAssignee.employee),
                selectinload(Task.comments).selectinload(TaskComment.author),
                selectinload(Task.events).selectinload(TaskEvent.actor),
            )
        )
    ).one()


def template_should_spawn(tpl: TaskTemplate, today: date) -> bool:
    if not tpl.active:
        return False
    if tpl.start_date and today < tpl.start_date:
        return False
    if tpl.last_spawned_on == today:
        return False

    rec = (tpl.recurrence or "daily").strip()
    val = (tpl.recurrence_value or "").strip()

    if rec == "daily":
        return True
    if rec == "every_n_days":
        n = int(val) if val.isdigit() else 1
        n = max(n, 1)
        if not tpl.last_spawned_on:
            return True
        return (today - tpl.last_spawned_on).days >= n
    if rec == "weekly":
        # one day: 1=Mon … 7=Sun in value, or use weekdays style
        days = [int(x) for x in val.split(",") if x.strip().isdigit()]
        wd = today.weekday() + 1
        return wd in days if days else wd == 1
    if rec == "weekdays":
        days = [int(x) for x in val.split(",") if x.strip().isdigit()]
        return (today.weekday() + 1) in days
    if rec == "monthly":
        day = int(val) if val.isdigit() else 1
        return today.day == day
    if rec == "month_days":
        days = [int(x) for x in val.split(",") if x.strip().isdigit()]
        return today.day in days
    return False


async def spawn_from_templates(session: AsyncSession, today: date) -> list[Task]:
    templates = (
        await session.scalars(select(TaskTemplate).where(TaskTemplate.active.is_(True)))
    ).all()
    created: list[Task] = []
    for tpl in templates:
        if not template_should_spawn(tpl, today):
            continue
        ids = [int(x) for x in (tpl.assignee_ids or "").split(",") if x.strip().isdigit()]
        task = Task(
            title=tpl.title,
            description=tpl.description or "",
            status="todo",
            kind="once",
            notify_time=tpl.notify_time or "09:00",
            due_date=today,
            template_id=tpl.id,
            created_at=datetime.utcnow(),
            assignee_id=ids[0] if ids else None,
        )
        session.add(task)
        await session.flush()
        if ids:
            await set_assignees(session, task, ids, log=False)
        await add_event(
            session,
            task.id,
            f"Создана из шаблона «{tpl.title}»",
            kind="created",
        )
        tpl.last_spawned_on = today
        created.append(task)
    if created:
        await session.commit()
    return created
