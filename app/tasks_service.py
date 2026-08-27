from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Employee, Task, TaskAssignee, TaskComment, TaskEvent, TaskTemplate

STATUS_LABEL = {"todo": "Новая", "doing": "В работе", "done": "Выполнено"}

_DEFAULT_DUE_DAYS = 3

_MONTHS_RU: dict[str, int] = {
    "января": 1,
    "январь": 1,
    "янв": 1,
    "февраля": 2,
    "февраль": 2,
    "фев": 2,
    "марта": 3,
    "март": 3,
    "мар": 3,
    "апреля": 4,
    "апрель": 4,
    "апр": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июн": 6,
    "июля": 7,
    "июль": 7,
    "июл": 7,
    "августа": 8,
    "август": 8,
    "авг": 8,
    "сентября": 9,
    "сентябрь": 9,
    "сент": 9,
    "сен": 9,
    "октября": 10,
    "октябрь": 10,
    "окт": 10,
    "ноября": 11,
    "ноябрь": 11,
    "ноя": 11,
    "декабря": 12,
    "декабрь": 12,
    "дек": 12,
}

# «на 10 сентября», «к 10 сент 2026», «срок 10 сентября»
_DATE_MONTH_RE = re.compile(
    r"(?i)(?:(?:на|к|до|срок[уа]?|deadline)\s+)?"
    r"(?<!\d)(\d{1,2})\s+"
    r"(января|январь|янв|"
    r"февраля|февраль|фев|"
    r"марта|март|мар|"
    r"апреля|апрель|апр|"
    r"мая|май|"
    r"июня|июнь|июн|"
    r"июля|июль|июл|"
    r"августа|август|авг|"
    r"сентября|сентябрь|сент|сен|"
    r"октября|октябрь|окт|"
    r"ноября|ноябрь|ноя|"
    r"декабря|декабрь|дек)"
    r"(?:\s+(\d{4}))?"
    r"(?!\w)"
)

# 10.09 / 10.09.2026 / 10/09/26
_DATE_DOT_RE = re.compile(
    r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?!\d)"
)

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _year_for_md(today: date, month: int, day: int, year: int | None) -> int:
    if year is not None:
        return year
    candidate = _safe_date(today.year, month, day)
    if candidate is None:
        return today.year
    # если дата уже прошла — следующий год
    if candidate < today:
        return today.year + 1
    return today.year


def parse_calendar_due(blob: str, today: date) -> date | None:
    """Вытащить календарную дату из текста: «на 10 сентября», «10.09.2026»."""
    text = (blob or "").strip().lower().replace("ё", "е")
    if not text:
        return None

    m = _DATE_MONTH_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _MONTHS_RU.get(m.group(2).lower().replace("ё", "е"))
        year_raw = m.group(3)
        year = int(year_raw) if year_raw else None
        if month and 1 <= day <= 31:
            y = _year_for_md(today, month, day, year)
            parsed = _safe_date(y, month, day)
            if parsed:
                return parsed

    m = _DATE_DOT_RE.search(text)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year_raw = m.group(3)
        year: int | None
        if year_raw:
            y = int(year_raw)
            if y < 100:
                y += 2000
            year = y
        else:
            year = None
        if 1 <= month <= 12 and 1 <= day <= 31:
            y = _year_for_md(today, month, day, year)
            parsed = _safe_date(y, month, day)
            if parsed:
                return parsed
    return None


def strip_due_phrase(text: str) -> str:
    """Убрать из названия фразу со сроком («на 10 сентября, …»)."""
    raw = (text or "").strip()
    if not raw:
        return raw
    cleaned = _DATE_MONTH_RE.sub(" ", raw)
    cleaned = _DATE_DOT_RE.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)\b(сегодня|завтра|послезавтра|today|tomorrow)\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bсрок[уа]?\b", " ", cleaned)
    cleaned = re.sub(r"\s*[,;:\-–—]+\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,;:-–—")
    return cleaned or raw


def resolve_due_date(
    today: date,
    *,
    text: str = "",
    explicit: date | None = None,
    hint: str | None = None,
) -> date:
    """Срок: явный → ISO/сегодня/завтра/календарь из текста → иначе +3 дня."""
    if explicit is not None:
        return explicit
    h = (hint or "").strip().lower().replace("ё", "е")
    iso = _ISO_RE.match(h)
    if iso:
        parsed = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if parsed:
            return parsed
    blob = f"{h} {text}".lower().replace("ё", "е")
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
    cal = parse_calendar_due(blob, today)
    if cal is not None:
        return cal
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
                selectinload(Task.theme),
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


async def spawn_from_templates(
    session: AsyncSession,
    today: date,
    *,
    now_hm: str | None = None,
) -> list[Task]:
    """Создаёт задачи из шаблонов только в нужный день и не раньше notify_time."""
    templates = (
        await session.scalars(select(TaskTemplate).where(TaskTemplate.active.is_(True)))
    ).all()
    created: list[Task] = []
    for tpl in templates:
        if not template_should_spawn(tpl, today):
            continue
        notify_hm = (tpl.notify_time or "09:00").strip() or "09:00"
        if now_hm is not None and notify_hm > now_hm:
            # ещё рано — дождёмся минуты с временем из шаблона
            continue
        ids = [int(x) for x in (tpl.assignee_ids or "").split(",") if x.strip().isdigit()]
        task = Task(
            title=tpl.title,
            description=tpl.description or "",
            status="todo",
            kind="once",
            notify_time=notify_hm,
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
