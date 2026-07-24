"""Утренний и вечерний дайджест задач менеджерам в Telegram."""

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

logger = logging.getLogger("task-digest")

STATUS_RU = {"todo": "новая", "doing": "в работе"}


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
) -> str | None:
    """kind: morning | evening. None = нечего слать."""
    if not todo and not doing:
        return None

    if kind == "morning":
        lines = [f"☀️ Доброе утро, <b>{name}</b>!", "", "Твои открытые задачи:"]
    else:
        lines = [
            f"🌙 Напоминание, <b>{name}</b>",
            "",
            "Не забудь про свои задачи к концу дня:",
        ]

    if todo:
        lines.append("")
        lines.append(f"🟡 <b>Новые</b> ({len(todo)}):")
        for t in todo:
            lines.append(f"• {t.title}{_format_due(t.due_date)}")
    if doing:
        lines.append("")
        lines.append(f"🔵 <b>В работе</b> ({len(doing)}):")
        for t in doing:
            lines.append(f"• {t.title}{_format_due(t.due_date)}")

    if kind == "evening":
        lines.append("")
        lines.append("Если что-то сделал — жми «Сделано» в задаче или напиши боту.")

    return "\n".join(lines)


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
    """kind: morning | evening."""
    if not bot:
        return {"ok": False, "error": "bot off"}
    if kind not in {"morning", "evening"}:
        return {"ok": False, "error": "bad kind"}

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
            text = build_digest_text(name=emp.name, todo=todo, doing=doing, kind=kind)
            if not text:
                skipped += 1
                continue
            try:
                await bot.send_message(int(emp.telegram_id), text, parse_mode="HTML")
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
