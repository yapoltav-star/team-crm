from __future__ import annotations

import logging
from datetime import date, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, Task, TaskRun

logger = logging.getLogger(__name__)


def done_kb(run_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Сделано", callback_data=f"done:{run_id}")]]
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
    text = (
        f"📋 Новая задача от <b>{author}</b>\n"
        f"<b>{task.title}</b>\n\n"
        "Жми «Сделано», когда выполнишь."
    )
    try:
        await bot.send_message(
            int(assignee.telegram_id),
            text,
            reply_markup=done_kb(run.id),
            parse_mode="HTML",
        )
        run.notified_at = datetime.utcnow()
        await session.commit()
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
