from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Employee, Task, TaskRun

logger = logging.getLogger(__name__)


def done_kb(run_id: int, task_id: int) -> InlineKeyboardMarkup:
    # both ids — if run row missing after redeploy we can still close the task
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сделано", callback_data=f"done:{run_id}:{task_id}")]
        ]
    )


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


async def notify_task_assignee(
    *,
    bot: Bot | None,
    session: AsyncSession,
    task: Task,
    due: date,
) -> tuple[bool, str | None]:
    """Send Telegram notification. Returns (ok, error_hint)."""
    if not bot:
        return False, "Бот не запущен на сервере"
    assignee: Employee | None = task.assignee
    if not assignee:
        return False, "У задачи нет исполнителя"
    if not assignee.telegram_id:
        return False, "У исполнителя не указан Telegram id"

    author = task.created_by.name if task.created_by else "кто-то"
    run = await ensure_run(session, task.id, due)
    if not run.id:
        await session.refresh(run)
    text = (
        f"📋 Новая задача от <b>{author}</b>\n"
        f"<b>{task.title}</b>\n\n"
        "Жми «Сделано», когда выполнишь."
    )
    try:
        await bot.send_message(
            int(assignee.telegram_id),
            text,
            reply_markup=done_kb(int(run.id), int(task.id)),
            parse_mode="HTML",
        )
        run.notified_at = datetime.utcnow()
        await session.commit()
        logger.info("notified task=%s run=%s user=%s", task.id, run.id, assignee.telegram_id)
        return True, None
    except TelegramForbiddenError:
        msg = (
            f"{assignee.name} ещё не открыл(а) бота. "
            "Пусть напишет боту /start, потом создай задачу снова "
            "или нажми «Повторить TG»."
        )
        logger.warning("notify forbidden task=%s user=%s", task.id, assignee.telegram_id)
        return False, msg
    except TelegramBadRequest as exc:
        msg = f"Telegram отклонил сообщение: {exc}"
        logger.warning("notify bad request task=%s: %s", task.id, exc)
        return False, msg
    except TelegramAPIError as exc:
        msg = f"Ошибка Telegram API: {exc}"
        logger.exception("notify api error task=%s", task.id)
        return False, msg
    except Exception as exc:  # noqa: BLE001
        logger.exception("notify failed task=%s", task.id)
        return False, f"Не удалось отправить: {exc}"


async def resolve_run(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_id: int | None,
) -> TaskRun | None:
    opts = (
        selectinload(TaskRun.task).selectinload(Task.assignee),
        selectinload(TaskRun.task).selectinload(Task.created_by),
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
            options=(selectinload(Task.assignee), selectinload(Task.created_by)),
        )
        if not task:
            return None
        # synthesize a run row so Done still works for older buttons / lost runs
        due = datetime.utcnow().date()
        run = await ensure_run(session, task.id, due)
        return await session.get(TaskRun, run.id, options=opts)
    return None
