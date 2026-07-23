from __future__ import annotations

import logging
import socket
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import TCPConnector
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Employee, Task, TaskRun

logger = logging.getLogger("crm-bot")


def _session(proxy: str | None) -> AiohttpSession:
    if proxy:
        return AiohttpSession(proxy=proxy)
    return AiohttpSession(connector=TCPConnector(family=socket.AF_INET))


def done_kb(run_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Сделано", callback_data=f"done:{run_id}")]]
    )


async def ensure_owner(session: AsyncSession, owner_id: int) -> Employee:
    emp = await session.scalar(select(Employee).where(Employee.telegram_id == owner_id))
    if emp:
        emp.role = "owner"
        emp.active = True
        await session.commit()
        return emp
    emp = Employee(telegram_id=owner_id, name="Владелец", role="owner")
    session.add(emp)
    await session.commit()
    await session.refresh(emp)
    return emp


async def _ensure_run(session: AsyncSession, task_id: int, due: date) -> TaskRun:
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


async def create_and_notify(
    *,
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    title: str,
    assignee: Employee,
    author: Employee,
    kind: str = "once",
    weekdays: str = "",
    notify_time: str | None = None,
) -> Task:
    task = Task(
        title=title,
        assignee_id=assignee.id,
        created_by_id=author.id,
        status="todo",
        kind=kind,
        weekdays=weekdays,
        notify_time=notify_time or datetime.now(settings.tz).strftime("%H:%M"),
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if kind == "once":
        run = await _ensure_run(session, task.id, datetime.now(settings.tz).date())
        text = (
            f"📋 Новая задача от <b>{author.name}</b>\n"
            f"<b>{title}</b>\n\n"
            "Жми «Сделано», когда выполнишь."
        )
        try:
            await bot.send_message(
                assignee.telegram_id,
                text,
                reply_markup=done_kb(run.id),
                parse_mode="HTML",
            )
            run.notified_at = datetime.utcnow()
            await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("send task failed")
    return task


async def materialize_and_notify(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    settings: Settings,
) -> None:
    now = datetime.now(settings.tz)
    today = now.date()
    weekday = now.weekday() + 1
    hm = now.strftime("%H:%M")

    async with session_factory() as session:
        await ensure_owner(session, settings.owner_telegram_id)
        weekly = (
            await session.scalars(select(Task).where(Task.active.is_(True), Task.kind == "weekly"))
        ).all()
        for task in weekly:
            days = [int(x) for x in (task.weekdays or "").split(",") if x.strip().isdigit()]
            if weekday in days:
                await _ensure_run(session, task.id, today)

        runs = (
            await session.scalars(
                select(TaskRun)
                .join(Task)
                .where(
                    TaskRun.status == "pending",
                    TaskRun.due_date == today,
                    TaskRun.notified_at.is_(None),
                    Task.active.is_(True),
                    Task.notify_time <= hm,
                )
                .options(
                    selectinload(TaskRun.task).selectinload(Task.assignee),
                    selectinload(TaskRun.task).selectinload(Task.created_by),
                )
            )
        ).all()
        for run in runs:
            task = run.task
            if not task or not task.assignee:
                continue
            author = task.created_by.name if task.created_by else "CRM"
            text = (
                f"📋 Задача на сегодня ({today.isoformat()}) от <b>{author}</b>\n"
                f"<b>{task.title}</b>\n\n"
                "Жми «Сделано», когда выполнишь."
            )
            try:
                await bot.send_message(
                    task.assignee.telegram_id,
                    text,
                    reply_markup=done_kb(run.id),
                    parse_mode="HTML",
                )
                run.notified_at = datetime.utcnow()
            except Exception:  # noqa: BLE001
                logger.exception("notify failed run=%s", run.id)
        await session.commit()

        if hm >= settings.escalate_time:
            pending = (
                await session.scalars(
                    select(TaskRun)
                    .join(Task)
                    .where(
                        TaskRun.status == "pending",
                        TaskRun.due_date == today,
                        Task.active.is_(True),
                        Task.notify_time <= hm,
                    )
                    .options(selectinload(TaskRun.task).selectinload(Task.assignee))
                )
            ).all()
            freshly = []
            for run in pending:
                run.status = "escalated"
                run.escalated_at = datetime.utcnow()
                if run.task and run.task.assignee:
                    freshly.append(f"• {run.task.assignee.name}: {run.task.title}")
            await session.commit()
            if freshly:
                try:
                    await bot.send_message(
                        settings.owner_telegram_id,
                        "⚠️ Не сделали задачи на сегодня:\n\n" + "\n".join(freshly),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("escalate failed")


def build_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Bot, Dispatcher]:
    bot = Bot(token=settings.telegram_bot_token, session=_session(settings.telegram_proxy))
    dp = Dispatcher()

    help_common = (
        "Команды для всех:\n"
        "/todo текст — задача себе\n"
        "/boss текст — задача владельцу\n"
        "/for <telegram_id> | текст — задача человеку\n"
        "/my — мои открытые\n"
    )

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        if not message.from_user:
            return
        async with session_factory() as session:
            if message.from_user.id == settings.owner_telegram_id:
                await ensure_owner(session, settings.owner_telegram_id)
                await message.answer(
                    "CRM-бот (владелец).\n"
                    "/add_manager <id> <Имя>\n"
                    "/task <id> | текст\n"
                    "/weekly <id> 1,3,5 10:00 | текст\n"
                    f"{help_common}"
                    "Канбан: сайт Railway."
                )
                return
            emp = await session.scalar(
                select(Employee).where(Employee.telegram_id == message.from_user.id)
            )
            if not emp:
                await message.answer("Нет доступа. Попроси владельца /add_manager.")
                return
            await message.answer(f"Привет, {emp.name}!\n{help_common}")

    async def _author(session: AsyncSession, telegram_id: int) -> Employee | None:
        if telegram_id == settings.owner_telegram_id:
            return await ensure_owner(session, settings.owner_telegram_id)
        return await session.scalar(select(Employee).where(Employee.telegram_id == telegram_id))

    @dp.message(Command("todo"))
    async def cmd_todo(message: Message, command: CommandObject) -> None:
        title = (command.args or "").strip()
        if not title or not message.from_user:
            await message.answer("Формат: /todo Сделать отчёт")
            return
        async with session_factory() as session:
            author = await _author(session, message.from_user.id)
            if not author:
                await message.answer("Нет доступа.")
                return
            await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=author,
                author=author,
            )
        await message.answer("Задача себе создана.")

    @dp.message(Command("boss"))
    async def cmd_boss(message: Message, command: CommandObject) -> None:
        title = (command.args or "").strip()
        if not title or not message.from_user:
            await message.answer("Формат: /boss Нужно согласовать закупку")
            return
        async with session_factory() as session:
            author = await _author(session, message.from_user.id)
            owner = await ensure_owner(session, settings.owner_telegram_id)
            if not author:
                await message.answer("Нет доступа.")
                return
            await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=owner,
                author=author,
            )
        await message.answer("Задача отправлена владельцу.")

    @dp.message(Command("for"))
    async def cmd_for(message: Message, command: CommandObject) -> None:
        raw = (command.args or "").strip()
        if "|" not in raw or not message.from_user:
            await message.answer("Формат: /for 123456 | текст задачи")
            return
        left, title = [x.strip() for x in raw.split("|", 1)]
        if not left.isdigit() or not title:
            await message.answer("Формат: /for 123456 | текст задачи")
            return
        async with session_factory() as session:
            author = await _author(session, message.from_user.id)
            assignee = await session.scalar(select(Employee).where(Employee.telegram_id == int(left)))
            if not author:
                await message.answer("Нет доступа.")
                return
            if not assignee:
                await message.answer("Человек не найден в CRM. Сначала /add_manager.")
                return
            await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=assignee,
                author=author,
            )
        await message.answer(f"Задача отправлена: {title}")

    @dp.message(Command("my"))
    async def cmd_my(message: Message) -> None:
        if not message.from_user:
            return
        async with session_factory() as session:
            emp = await _author(session, message.from_user.id)
            if not emp:
                await message.answer("Нет доступа.")
                return
            tasks = (
                await session.scalars(
                    select(Task).where(
                        Task.assignee_id == emp.id,
                        Task.active.is_(True),
                        Task.status != "done",
                    )
                )
            ).all()
        if not tasks:
            await message.answer("Открытых задач нет.")
            return
        lines = [f"• {t.title} [{t.status}]" for t in tasks]
        await message.answer("Твои задачи:\n" + "\n".join(lines))

    @dp.message(Command("add_manager"))
    async def add_manager(message: Message, command: CommandObject) -> None:
        if not message.from_user or message.from_user.id != settings.owner_telegram_id:
            await message.answer("Только владелец.")
            return
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            await message.answer("Формат: /add_manager <telegram_id> <Имя>")
            return
        async with session_factory() as session:
            tid = int(parts[0])
            name = parts[1].strip()
            emp = await session.scalar(select(Employee).where(Employee.telegram_id == tid))
            if emp:
                emp.name = name
                emp.role = "manager"
                emp.active = True
            else:
                session.add(Employee(telegram_id=tid, name=name, role="manager"))
            await session.commit()
        await message.answer(f"Менеджер {parts[1]} добавлен.")
        try:
            await message.bot.send_message(
                int(parts[0]),
                f"Тебя добавили в CRM как {parts[1]}.\n/start",
            )
        except Exception:  # noqa: BLE001
            pass

    @dp.message(Command("task"))
    async def once_task(message: Message, command: CommandObject) -> None:
        if not message.from_user or message.from_user.id != settings.owner_telegram_id:
            await message.answer("Только владелец. Менеджерам: /todo /boss /for")
            return
        raw = (command.args or "").strip()
        if "|" not in raw:
            await message.answer("Формат: /task <telegram_id> | текст")
            return
        left, title = [x.strip() for x in raw.split("|", 1)]
        if not left.isdigit() or not title:
            await message.answer("Формат: /task <telegram_id> | текст")
            return
        async with session_factory() as session:
            author = await ensure_owner(session, settings.owner_telegram_id)
            emp = await session.scalar(select(Employee).where(Employee.telegram_id == int(left)))
            if not emp:
                await message.answer("Сначала /add_manager")
                return
            await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=emp,
                author=author,
            )
        await message.answer("Задача создана и отправлена.")

    @dp.message(Command("weekly"))
    async def weekly_task(message: Message, command: CommandObject) -> None:
        if not message.from_user or message.from_user.id != settings.owner_telegram_id:
            await message.answer("Только владелец.")
            return
        raw = (command.args or "").strip()
        if "|" not in raw:
            await message.answer("Формат: /weekly <id> 1,3,5 10:00 | текст")
            return
        left, title = [x.strip() for x in raw.split("|", 1)]
        parts = left.split()
        if len(parts) != 3 or not parts[0].isdigit():
            await message.answer("Формат: /weekly <id> 1,3,5 10:00 | текст")
            return
        async with session_factory() as session:
            author = await ensure_owner(session, settings.owner_telegram_id)
            emp = await session.scalar(select(Employee).where(Employee.telegram_id == int(parts[0])))
            if not emp:
                await message.answer("Сначала /add_manager")
                return
            await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=emp,
                author=author,
                kind="weekly",
                weekdays=parts[1],
                notify_time=parts[2],
            )
        await message.answer(f"Еженедельная задача создана: {title}")

    @dp.callback_query(F.data.startswith("done:"))
    async def on_done(callback: CallbackQuery) -> None:
        if not callback.data or not callback.from_user:
            return
        run_id = int(callback.data.split(":", 1)[1])
        notify_ids: set[int] = set()
        name = "?"
        title = ""
        async with session_factory() as session:
            run = await session.scalar(
                select(TaskRun)
                .where(TaskRun.id == run_id)
                .options(
                    selectinload(TaskRun.task).selectinload(Task.assignee),
                    selectinload(TaskRun.task).selectinload(Task.created_by),
                )
            )
            if not run or not run.task:
                await callback.answer("Не найдено", show_alert=True)
                return
            assignee = run.task.assignee
            if (
                assignee
                and callback.from_user.id not in {assignee.telegram_id, settings.owner_telegram_id}
            ):
                await callback.answer("Не твоя задача", show_alert=True)
                return
            run.status = "done"
            run.completed_at = datetime.utcnow()
            if run.task.status != "done":
                run.task.status = "done"
            await session.commit()
            name = assignee.name if assignee else "?"
            title = run.task.title
            notify_ids.add(settings.owner_telegram_id)
            if run.task.created_by:
                notify_ids.add(run.task.created_by.telegram_id)
        await callback.answer("Готово ✅")
        if callback.message:
            try:
                await callback.message.edit_text(f"✅ Сделано: {title}")
            except Exception:  # noqa: BLE001
                pass
        for tid in notify_ids:
            if tid == callback.from_user.id:
                continue
            try:
                await callback.bot.send_message(tid, f"✅ {name} сделал(а): {title}")
            except Exception:  # noqa: BLE001
                pass

    return bot, dp
