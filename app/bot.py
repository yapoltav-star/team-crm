from __future__ import annotations

import logging
import socket
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Employee, Task, TaskRun
from app.notify import done_kb, ensure_run, notify_task_assignee

logger = logging.getLogger("crm-bot")


def _session(proxy: str | None) -> AiohttpSession:
    # aiogram 3.x: never pass connector= (BaseSession rejects it → startup crash).
    # Prefer IPv4 via _connector_init — Telegram IPv6 often flakes from RU/cloud.
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    init = getattr(session, "_connector_init", None)
    if isinstance(init, dict):
        init["family"] = socket.AF_INET
    return session


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
) -> tuple[Task, bool, str | None]:
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
    task = (
        await session.scalars(
            select(Task)
            .where(Task.id == task.id)
            .options(selectinload(Task.assignee), selectinload(Task.created_by))
        )
    ).one()

    ok, err = True, None
    if kind == "once":
        ok, err = await notify_task_assignee(
            bot=bot,
            session=session,
            task=task,
            due=datetime.now(settings.tz).date(),
        )
        if not ok and err:
            logger.warning("bot notify failed: %s", err)
    return task, ok, err

async def _reply_created(message: Message, ok: bool, err: str | None, ok_text: str) -> None:
    if ok:
        await message.answer(ok_text)
    else:
        await message.answer(ok_text + "\n\n⚠️ В Telegram не ушло: " + (err or "неизвестно"))

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
                await ensure_run(session, task.id, today)

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
        "Можно писать обычным текстом или голосом.\n"
        "Команды:\n"
        "/todo текст — себе\n"
        "/boss текст — владельцу\n"
        "/for <id> | текст — человеку\n"
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
            _, ok, err = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=author,
                author=author,
            )
        await _reply_created(message, ok, err, "Задача себе создана.")

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
            _, ok, err = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=owner,
                author=author,
            )
        await _reply_created(message, ok, err, "Задача отправлена владельцу.")

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
            _, ok, err = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=assignee,
                author=author,
            )
        await _reply_created(message, ok, err, f"Задача отправлена: {title}")

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
            _, ok, err = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=emp,
                author=author,
            )
        await _reply_created(message, ok, err, "Задача создана и отправлена.")

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

    def _match_assignee(people: list[Employee], token: str, author: Employee) -> Employee | None:
        t = (token or "").strip().lower()
        if t in {"me", "себе", "мне", "я"}:
            return author
        if t in {"boss", "босс", "владелец", "директор", "директору", "шефу", "owner"}:
            return next((p for p in people if p.role == "owner"), None)
        for p in people:
            if t and t in p.name.lower():
                return p
        return None

    async def _handle_natural(message: Message, text: str) -> None:
        if not message.from_user or not text.strip():
            return
        if not settings.nlp_enabled:
            await message.answer(
                "Пока доступны только команды. Добавь OPENAI_API_KEY в Railway — заработает текст/голос.\n"
                f"{help_common}"
            )
            return
        wait = await message.answer("Понял, думаю…")
        try:
            async with session_factory() as session:
                author = await _author(session, message.from_user.id)
                if not author:
                    await wait.edit_text("Нет доступа. Попроси /add_manager.")
                    return
                people = (
                    await session.scalars(select(Employee).where(Employee.active.is_(True)))
                ).all()
                from app.nlp import parse_intent

                intent = await parse_intent(
                    settings,
                    text=text,
                    author_name=author.name,
                    people=[{"name": p.name, "role": p.role} for p in people],
                )
                action = intent.get("action")
                if action == "create_task":
                    title = str(intent.get("title") or "").strip()
                    token = str(intent.get("assignee") or "me")
                    if not title:
                        await wait.edit_text("Не увидел текст задачи. Сформулируй ещё раз.")
                        return
                    assignee = _match_assignee(list(people), token, author)
                    if not assignee:
                        await wait.edit_text(
                            f"Не понял, кому задача («{token}»). Назови имя из команды или скажи «себе»/«боссу»."
                        )
                        return
                    _, ok, err = await create_and_notify(
                        session=session,
                        bot=message.bot,
                        settings=settings,
                        title=title,
                        assignee=assignee,
                        author=author,
                    )
                    text = f"Готово: задача для {assignee.name}\n«{title}»"
                    if not ok:
                        text += f"\n\n⚠️ В Telegram не ушло: {err or 'неизвестно'}"
                    await wait.edit_text(text)
                    return
                if action == "list_my_tasks":
                    tasks = (
                        await session.scalars(
                            select(Task).where(
                                Task.assignee_id == author.id,
                                Task.active.is_(True),
                                Task.status != "done",
                            )
                        )
                    ).all()
                    if not tasks:
                        await wait.edit_text("Открытых задач нет.")
                        return
                    lines = [f"• {t.title} [{t.status}]" for t in tasks]
                    await wait.edit_text("Твои задачи:\n" + "\n".join(lines))
                    return
                if action == "help":
                    await wait.edit_text(help_common)
                    return
                await wait.edit_text(str(intent.get("reply") or help_common))
        except Exception as exc:  # noqa: BLE001
            logger.exception("nlp failed")
            await wait.edit_text(f"Не смог разобрать: {exc}")

    @dp.message(F.voice)
    async def on_voice(message: Message) -> None:
        if not settings.nlp_enabled:
            await message.answer("Голос заработает после OPENAI_API_KEY в Railway.")
            return
        if not message.voice:
            return
        file = await message.bot.get_file(message.voice.file_id)
        buf = await message.bot.download_file(file.file_path)
        ogg = buf.read() if hasattr(buf, "read") else bytes(buf)
        from app.nlp import transcribe_voice

        try:
            text = await transcribe_voice(settings, ogg)
        except Exception as exc:  # noqa: BLE001
            logger.exception("whisper failed")
            await message.answer(f"Не распознал голос: {exc}")
            return
        if not text:
            await message.answer("Пустая расшифровка, повтори.")
            return
        await message.answer(f"Распознал: {text}")
        await _handle_natural(message, text)

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        await _handle_natural(message, message.text)

    return bot, dp
