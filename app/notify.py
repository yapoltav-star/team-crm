from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Employee, Task, TaskAssignee, TaskComment, TaskRun

logger = logging.getLogger(__name__)


def task_action_kb(
    run_id: int, task_id: int, *, status: str = "todo"
) -> InlineKeyboardMarkup:
    """Кнопки статуса: В работе / Сделано + комментарий."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    if status != "doing" and status != "done":
        row.append(
            InlineKeyboardButton(
                text="🔵 В работе",
                callback_data=f"doing:{run_id}:{task_id}",
            )
        )
    if status != "done":
        row.append(
            InlineKeyboardButton(
                text="✅ Сделано",
                callback_data=f"done:{run_id}:{task_id}",
            )
        )
    if row:
        rows.append(row)
    if status != "done":
        rows.append(
            [
                InlineKeyboardButton(
                    text="💬 Комментарий",
                    callback_data=f"comment:{run_id}:{task_id}",
                )
            ]
        )
    if not rows:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ask_comment_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"askc:yes:{task_id}"),
                InlineKeyboardButton(text="Нет", callback_data=f"askc:no:{task_id}"),
            ]
        ]
    )


# обратная совместимость импортов
def done_kb(run_id: int, task_id: int) -> InlineKeyboardMarkup:
    return task_action_kb(run_id, task_id, status="todo")


async def ensure_run(session: AsyncSession, task_id: int, due: date) -> TaskRun:
    existing = await session.scalar(
        select(TaskRun).where(TaskRun.task_id == task_id, TaskRun.due_date == due)
    )
    if existing:
        return existing
    run = TaskRun(task_id=task_id, due_date=due, status="pending")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def _targets(task: Task) -> list[Employee]:
    people: list[Employee] = []
    seen: set[int] = set()
    for link in task.assignees or []:
        if link.employee and link.employee_id not in seen:
            seen.add(link.employee_id)
            people.append(link.employee)
    if task.assignee and task.assignee.id not in seen:
        people.append(task.assignee)
    return people


def format_due(d: date | None) -> str:
    if not d:
        return ""
    return f"\nСрок: <b>{d.strftime('%d.%m.%Y')}</b>"


async def notify_task_assignee(
    *,
    bot: Bot | None,
    session: AsyncSession,
    task: Task,
    due: date,
    employees: list[Employee] | None = None,
) -> tuple[bool, str | None]:
    if not bot:
        return False, "Бот не запущен на сервере"
    # явный список важнее — чтобы «всем» точно ушло каждому
    if employees:
        seen: set[int] = set()
        targets: list[Employee] = []
        for emp in employees:
            if emp and emp.id not in seen:
                seen.add(emp.id)
                targets.append(emp)
    else:
        targets = _targets(task)
    if not targets:
        return False, "У задачи нет исполнителя"

    author = task.created_by.name if task.created_by else "кто-то"
    run = await ensure_run(session, task.id, due)
    if not run.id:
        await session.refresh(run)
    sku_line = ""
    if (task.articles or "").strip():
        codes = ", ".join(x.strip() for x in task.articles.split(",") if x.strip())
        sku_line = f"\nАртикул: <code>{codes}</code>"
    due_line = format_due(task.due_date or due)
    text = (
        f"📋 Новая задача от <b>{author}</b>\n"
        f"<b>{task.title}</b>{sku_line}{due_line}\n\n"
        "Жми «В работе», «Сделано» или «Комментарий»."
    )

    errors: list[str] = []
    sent = 0
    for emp in targets:
        if not emp.telegram_id:
            errors.append(f"{emp.name}: нет Telegram id")
            continue
        try:
            await bot.send_message(
                int(emp.telegram_id),
                text,
                reply_markup=task_action_kb(int(run.id), int(task.id), status=task.status or "todo"),
                parse_mode="HTML",
            )
            sent += 1
        except TelegramForbiddenError:
            errors.append(f"{emp.name}: не нажал /start")
        except (TelegramBadRequest, TelegramAPIError) as exc:
            errors.append(f"{emp.name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("notify failed task=%s user=%s", task.id, emp.telegram_id)
            errors.append(f"{emp.name}: {exc}")

    if sent:
        run.notified_at = datetime.utcnow()
        await session.commit()
    if sent and not errors:
        return True, None
    if sent and errors:
        return True, "Частично: " + "; ".join(errors)
    return False, "; ".join(errors) or "Не удалось отправить"


async def resolve_run(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_id: int | None,
) -> TaskRun | None:
    opts = (
        selectinload(TaskRun.task).selectinload(Task.assignee),
        selectinload(TaskRun.task).selectinload(Task.created_by),
        selectinload(TaskRun.task).selectinload(Task.assignees).selectinload(TaskAssignee.employee),
    )
    if run_id:
        run = await session.get(TaskRun, run_id, options=opts)
        if run and run.task:
            return run
    if task_id:
        run = await session.scalar(
            select(TaskRun)
            .where(TaskRun.task_id == task_id)
            .options(*opts)
            .order_by(TaskRun.id.desc())
        )
        if run and run.task:
            return run
        task = await session.get(
            Task,
            task_id,
            options=(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.assignees).selectinload(TaskAssignee.employee),
            ),
        )
        if not task:
            return None
        due = task.due_date or datetime.utcnow().date()
        run = await ensure_run(session, task.id, due)
        return await session.get(TaskRun, run.id, options=opts)
    return None


async def save_task_comment(
    session: AsyncSession,
    *,
    task_id: int,
    author: Employee,
    body: str,
) -> TaskComment | None:
    text = (body or "").strip()
    if not text:
        return None
    from app.tasks_service import add_event

    c = TaskComment(
        task_id=task_id,
        author_id=author.id,
        body=text[:4000],
        created_at=datetime.utcnow(),
    )
    session.add(c)
    await add_event(
        session,
        task_id,
        f"Комментарий — {author.name}",
        kind="comment",
        actor_id=author.id,
    )
    await session.commit()
    await session.refresh(c)
    return c


async def notify_task_comment(
    *,
    bot: Bot | None,
    task: Task,
    author: Employee,
    body: str,
) -> None:
    """Комментарий уходит тому, кто ставил задачу; если пишет постановщик — исполнителям."""
    if not bot:
        return
    text = (
        f"💬 Комментарий к задаче <b>{task.title}</b>\n"
        f"от <b>{author.name}</b>:\n{body.strip()}"
    )
    recipients: list[Employee] = []
    seen: set[int] = set()

    def _add(emp: Employee | None) -> None:
        if not emp or not emp.telegram_id:
            return
        tid = int(emp.telegram_id)
        if tid in seen or emp.id == author.id:
            return
        seen.add(tid)
        recipients.append(emp)

    if task.created_by_id and author.id != task.created_by_id:
        _add(task.created_by)
    else:
        for emp in _targets(task):
            _add(emp)

    for emp in recipients:
        try:
            await bot.send_message(int(emp.telegram_id), text, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            logger.exception(
                "comment notify failed task=%s user=%s", task.id, emp.telegram_id
            )
