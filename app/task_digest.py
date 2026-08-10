"""Утренний / обеденный / вечерний дайджест задач менеджерам в Telegram.

Задачи со сроком «сегодня» напоминаем во все три слота.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Employee, Task, TaskAssignee
from app.notify import my_tasks_done_kb

logger = logging.getLogger("task-digest")

STATUS_RU = {"todo": "новая", "doing": "в работе"}
DIGEST_KINDS = frozenset({"morning", "midday", "evening"})


def _parse_hm(raw: str, default: tuple[int, int] = (9, 0)) -> tuple[int, int]:
    try:
        parts = (raw or "").strip().split(":")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except Exception:  # noqa: BLE001
        return default


def _task_belongs(task: Task, emp_id: int) -> bool:
    if task.assignee_id == emp_id:
        return True
    return any(a.employee_id == emp_id for a in (task.assignees or []))


def _format_due(d: date | None) -> str:
    if not d:
        return ""
    return f" · до {d.strftime('%d.%m.%Y')}"


def build_digest_text(
    *,
    name: str,
    todo: list[Task],
    doing: list[Task],
    kind: str,
    today: date,
) -> str | None:
    """kind: morning | midday | evening. None = нечего слать."""
    open_tasks = [*todo, *doing]
    due_today = [t for t in open_tasks if t.due_date == today]
    other_todo = [t for t in todo if t.due_date != today]
    other_doing = [t for t in doing if t.due_date != today]

    # обед — только задачи на сегодня
    if kind == "midday":
        if not due_today:
            return None
        lines = [
            f"🍽 Обед, <b>{name}</b>",
            "",
            f"На сегодня ещё не закрыто ({len(due_today)}):",
            "",
        ]
        for t in due_today:
            st = STATUS_RU.get(t.status, t.status)
            lines.append(f"• {t.title} — {st}")
        lines.append("")
        lines.append("Жми ✅ ниже или «Сделано» в задаче.")
        return "\n".join(lines)

    if not open_tasks:
        return None

    if kind == "morning":
        lines = [f"☀️ Доброе утро, <b>{name}</b>!", ""]
    else:
        lines = [f"🌙 Напоминание, <b>{name}</b>", ""]

    if due_today:
        lines.append(f"🔥 <b>На сегодня</b> ({len(due_today)}):")
        for t in due_today:
            st = STATUS_RU.get(t.status, t.status)
            lines.append(f"• {t.title} — {st}")
        lines.append("")
    elif kind == "evening":
        lines.append("На сегодня срочных нет.")
        lines.append("")

    if other_todo:
        lines.append(f"🟡 <b>Новые</b> ({len(other_todo)}):")
        for t in other_todo:
            lines.append(f"• {t.title}{_format_due(t.due_date)}")
        lines.append("")
    if other_doing:
        lines.append(f"🔵 <b>В работе</b> ({len(other_doing)}):")
        for t in other_doing:
            lines.append(f"• {t.title}{_format_due(t.due_date)}")
        lines.append("")

    if kind == "evening":
        lines.append("Если сделал — жми ✅ ниже или напиши боту «закрой задачу…».")
    elif due_today:
        lines.append("Задачи на сегодня — кнопки ✅ ниже.")

    # если только заголовок без задач (не должно случиться)
    body = "\n".join(lines).strip()
    return body or None


async def _open_tasks_for(
    session: AsyncSession, emp: Employee
) -> tuple[list[Task], list[Task]]:
    tasks = (
        await session.scalars(
            select(Task)
            .where(
                Task.active.is_(True),
                Task.archived_at.is_(None),
                Task.status.in_(("todo", "doing")),
            )
            .options(
                selectinload(Task.assignee),
                selectinload(Task.assignees),
            )
            .order_by(Task.due_date.nulls_last(), Task.id)
        )
    ).all()
    mine = [t for t in tasks if _task_belongs(t, emp.id)]
    todo = [t for t in mine if t.status == "todo"]
    doing = [t for t in mine if t.status == "doing"]
    return todo, doing


async def send_task_digests(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    bot: Bot | None,
    kind: str,
) -> dict:
    """kind: morning | midday | evening."""
    if not bot:
        return {"ok": False, "error": "bot off"}
    if kind not in DIGEST_KINDS:
        return {"ok": False, "error": "bad kind"}

    today = datetime.now(settings.tz).date()
    sent = 0
    skipped = 0
    errors: list[str] = []

    async with session_factory() as session:
        people = (
            await session.scalars(
                select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)
            )
        ).all()
        for emp in people:
            if not emp.telegram_id:
                skipped += 1
                continue
            todo, doing = await _open_tasks_for(session, emp)
            text = build_digest_text(
                name=emp.name,
                todo=todo,
                doing=doing,
                kind=kind,
                today=today,
            )
            if not text:
                skipped += 1
                continue
            due_today = [
                t
                for t in (*todo, *doing)
                if t.due_date == today
            ]
            # кнопки «выполнено» — по задачам на сегодня (удобно закрыть из дайджеста)
            kb = (
                my_tasks_done_kb(due_today, list_owner_id=emp.id)
                if due_today
                else None
            )
            try:
                await bot.send_message(
                    int(emp.telegram_id),
                    text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
                sent += 1
            except TelegramForbiddenError:
                errors.append(f"{emp.name}: /start")
            except (TelegramBadRequest, TelegramAPIError) as exc:
                errors.append(f"{emp.name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("digest failed emp=%s", emp.id)
                errors.append(f"{emp.name}: {exc}")

    result = {
        "ok": True,
        "kind": kind,
        "sent": sent,
        "skipped": skipped,
        "errors": errors[:10],
        "at": datetime.utcnow().isoformat() + "Z",
    }
    logger.info("task_digest %s", result)
    return result
