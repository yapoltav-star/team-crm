from __future__ import annotations

import logging
import re
import socket
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Employee, Task, TaskAssignee, TaskRun
from app.notify import ensure_run, notify_task_assignee, resolve_run, task_action_kb
from app.tasks_service import resolve_due_date

logger = logging.getLogger("crm-bot")


class JoinForm(StatesGroup):
    waiting_name = State()


def join_kb(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Добавить в команду",
                    callback_data=f"join:ok:{telegram_id}",
                ),
                InlineKeyboardButton(
                    text="✕ Отклонить",
                    callback_data=f"join:no:{telegram_id}",
                ),
            ]
        ]
    )


def _tg_name(user: User) -> str:
    name = (user.full_name or user.username or f"User {user.id}").strip()
    return name[:200] or f"User {user.id}"


async def find_employee(session: AsyncSession, telegram_id: int) -> Employee | None:
    tid = int(telegram_id)
    emp = await session.scalar(select(Employee).where(Employee.telegram_id == tid))
    if emp:
        return emp
    # fallback если в БД тип/значение сравнилось криво
    for row in (await session.scalars(select(Employee))).all():
        try:
            if int(row.telegram_id) == tid:
                return row
        except (TypeError, ValueError):
            continue
    return None


async def ensure_member(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    create_if_missing: bool = False,
) -> Employee | None:
    """Вернуть активного сотрудника. Новых сам не создаёт — только через заявку/владельца."""
    tid = int(user.id)
    name = _tg_name(user)
    if tid == int(settings.owner_telegram_id):
        return await ensure_owner(session, tid, display_name=name)

    emp = await find_employee(session, tid)
    if emp and emp.active:
        if not emp.name or emp.name.startswith("User ") or emp.name.strip().lower() in {
            "владелец",
            "owner",
        }:
            emp.name = name
            await session.commit()
        return emp

    if emp and not emp.active:
        return None

    if not create_if_missing or not settings.allow_self_join:
        return None

    emp = Employee(telegram_id=tid, name=name, role="manager", active=True)
    session.add(emp)
    await session.commit()
    await session.refresh(emp)
    logger.info("self-join manager id=%s telegram_id=%s name=%s", emp.id, tid, name)
    return emp


def _session(proxy: str | None) -> AiohttpSession:
    # aiogram 3.x: never pass connector= (BaseSession rejects it → startup crash).
    # Prefer IPv4 via _connector_init — Telegram IPv6 often flakes from RU/cloud.
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    init = getattr(session, "_connector_init", None)
    if isinstance(init, dict):
        init["family"] = socket.AF_INET
    return session


async def ensure_owner(
    session: AsyncSession,
    owner_id: int,
    display_name: str | None = None,
) -> Employee:
    tid = int(owner_id)
    emp = await find_employee(session, tid)
    placeholder = {"владелец", "owner", ""}
    if emp:
        emp.role = "owner"
        emp.active = True
        emp.telegram_id = tid
        if display_name and (not emp.name or emp.name.strip().lower() in placeholder):
            emp.name = display_name[:200]
        await session.commit()
        return emp
    emp = Employee(
        telegram_id=tid,
        name=(display_name or "Ярослав")[:200],
        role="owner",
        active=True,
    )
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
    author: Employee,
    assignee: Employee | None = None,
    assignees: list[Employee] | None = None,
    kind: str = "once",
    weekdays: str = "",
    notify_time: str | None = None,
    articles: str = "",
    due_date: date | None = None,
    due_hint: str | None = None,
) -> tuple[Task | None, bool, str | None, str | None]:
    """Returns (task, notify_ok, notify_err, clarify_msg). clarify_msg => task not created."""
    from app.catalog import load_catalog
    from app.sku import enrich_task_text

    targets: list[Employee] = []
    seen: set[int] = set()
    for emp in list(assignees or []) + ([assignee] if assignee else []):
        if emp and emp.id not in seen:
            seen.add(emp.id)
            targets.append(emp)
    if not targets:
        return None, False, "Нет исполнителей", None

    catalog = await load_catalog(session)
    title2, arts, clarify = enrich_task_text(title, catalog)
    if clarify:
        return None, False, None, clarify
    if arts:
        articles = arts
    title = title2

    from app.tasks_service import add_event, set_assignees

    today = datetime.now(settings.tz).date()
    due = None
    if kind == "once":
        due = resolve_due_date(today, text=title, explicit=due_date, hint=due_hint)
    primary = targets[0]
    task = Task(
        title=title,
        articles=articles or "",
        assignee_id=primary.id,
        created_by_id=author.id,
        status="todo",
        kind=kind,
        weekdays=weekdays,
        notify_time=notify_time or datetime.now(settings.tz).strftime("%H:%M"),
        due_date=due,
    )
    session.add(task)
    await session.commit()
    task = (
        await session.scalars(
            select(Task)
            .where(Task.id == task.id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.assignees),
            )
        )
    ).one()
    await set_assignees(
        session, task, [e.id for e in targets], actor_id=author.id, log=True
    )
    await add_event(
        session, task.id, f"Создана — {author.name}", kind="created", actor_id=author.id
    )
    await session.commit()
    task = (
        await session.scalars(
            select(Task)
            .where(Task.id == task.id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.created_by),
                selectinload(Task.assignees).selectinload(TaskAssignee.employee),
            )
        )
    ).one()

    ok, err = True, None
    if kind == "once":
        ok, err = await notify_task_assignee(
            bot=bot,
            session=session,
            task=task,
            due=task.due_date or today,
        )
        if not ok and err:
            logger.warning("bot notify failed: %s", err)
    return task, ok, err, None

async def _reply_created(message: Message, ok: bool, err: str | None, ok_text: str) -> None:
    if ok:
        await message.answer(ok_text)
    else:
        await message.answer(ok_text + "\n\n⚠️ В Telegram не ушло: " + (err or "неизвестно"))


STATUS_RU = {"todo": "новая", "doing": "в работе", "done": "выполнено"}


async def format_open_tasks(
    session: AsyncSession,
    *,
    people: list[Employee] | None = None,
    assignee: Employee | None = None,
) -> str:
    """Open tasks for one person or the whole team."""
    q = (
        select(Task)
        .where(Task.active.is_(True), Task.status != "done")
        .options(
            selectinload(Task.assignee),
            selectinload(Task.created_by),
            selectinload(Task.assignees),
        )
        .order_by(Task.status, Task.id)
    )
    tasks = (await session.scalars(q)).all()
    if assignee is not None:
        tasks = [
            t
            for t in tasks
            if t.assignee_id == assignee.id
            or any(a.employee_id == assignee.id for a in (t.assignees or []))
        ]
    if assignee is not None:
        if not tasks:
            return f"У {assignee.name} открытых задач нет."
        lines = [f"Задачи — {assignee.name}:"]
        for t in tasks:
            st = STATUS_RU.get(t.status, t.status)
            author = f" (от {t.created_by.name})" if t.created_by else ""
            lines.append(f"• {t.title} — {st}{author}")
        return "\n".join(lines)

    team = people or []
    by_id: dict[int, list[Task]] = {}
    for t in tasks:
        if t.assignee_id is None:
            continue
        by_id.setdefault(t.assignee_id, []).append(t)

    if not team and not by_id:
        return "Открытых задач пока нет."

    blocks: list[str] = ["Кто чем занят:"]
    ordered = sorted(team, key=lambda e: (e.role != "owner", e.name.lower()))
    seen: set[int] = set()
    for emp in ordered:
        seen.add(emp.id)
        items = by_id.get(emp.id, [])
        if not items:
            blocks.append(f"\n{emp.name}: —")
            continue
        blocks.append(f"\n{emp.name} ({len(items)}):")
        for t in items:
            st = STATUS_RU.get(t.status, t.status)
            blocks.append(f"• {t.title} — {st}")
    for emp_id, items in by_id.items():
        if emp_id in seen:
            continue
        name = items[0].assignee.name if items[0].assignee else f"#{emp_id}"
        blocks.append(f"\n{name} ({len(items)}):")
        for t in items:
            st = STATUS_RU.get(t.status, t.status)
            blocks.append(f"• {t.title} — {st}")
    return "\n".join(blocks)

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
        from app.tasks_service import spawn_from_templates

        spawned = await spawn_from_templates(session, today)
        for task in spawned:
            try:
                full = (
                    await session.scalars(
                        select(Task)
                        .where(Task.id == task.id)
                        .options(
                            selectinload(Task.assignee),
                            selectinload(Task.created_by),
                            selectinload(Task.assignees).selectinload(TaskAssignee.employee),
                        )
                    )
                ).one()
                await notify_task_assignee(bot=bot, session=session, task=full, due=today)
            except Exception:  # noqa: BLE001
                logger.exception("template notify failed task=%s", task.id)

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
                "Жми «В работе» или «Сделано»."
            )
            try:
                await bot.send_message(
                    task.assignee.telegram_id,
                    text,
                    reply_markup=task_action_kb(
                        int(run.id), int(task.id), status=task.status or "todo"
                    ),
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
    dp = Dispatcher(storage=MemoryStorage())

    help_common = (
        "Можно писать обычным текстом или голосом.\n"
        "Например: «у кого какие задачи», «что у Ивана».\n"
        "Команды:\n"
        "/todo текст — себе\n"
        "/boss текст — владельцу\n"
        "/for <id> | текст — человеку\n"
        "Или текстом: «поставь задачу всем проверить отзывы»\n"
        "/my — мои открытые\n"
        "/team — у кого что\n"
        "/name Имя — как тебя зовут в CRM\n"
    )

    @dp.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        if not message.from_user:
            return
        await state.clear()
        tid = int(message.from_user.id)
        async with session_factory() as session:
            if tid == int(settings.owner_telegram_id):
                emp = await ensure_owner(
                    session, tid, display_name=_tg_name(message.from_user)
                )
                await message.answer(
                    "CRM-бот (владелец).\n"
                    "Когда кто-то напишет /start и имя — придёт заявка с кнопкой «Добавить».\n"
                    "Или вручную: /add_manager <id> <Имя>\n"
                    "/task <id> | текст\n"
                    "/weekly <id> 1,3,5 10:00 | текст\n"
                    f"{help_common}"
                    "Канбан: сайт Railway."
                )
                return

            emp = await find_employee(session, tid)
            if emp and emp.active:
                await message.answer(f"Привет, {emp.name}! Ты в команде.\n{help_common}")
                return

            if emp and not emp.active:
                await message.answer(
                    f"Заявка уже отправлена владельцу (имя: {emp.name}).\n"
                    "Жди подтверждения — или напиши другое имя, если ошибся."
                )
                await state.set_state(JoinForm.waiting_name)
                return

            await state.set_state(JoinForm.waiting_name)
            await message.answer(
                "Привет! Чтобы попасть в команду, напиши своё имя.\n"
                "Например: <b>Иван</b>",
                parse_mode="HTML",
            )

    @dp.message(StateFilter(JoinForm.waiting_name), F.text)
    async def join_name(message: Message, state: FSMContext) -> None:
        if not message.from_user or not message.text:
            return
        name = message.text.strip()
        if name.startswith("/"):
            await message.answer("Просто напиши имя без команды. Например: Иван")
            return
        if len(name) < 2:
            await message.answer("Слишком коротко. Напиши имя нормально.")
            return
        name = name[:200]
        tid = int(message.from_user.id)
        uname = f"@{message.from_user.username}" if message.from_user.username else "—"

        async with session_factory() as session:
            emp = await find_employee(session, tid)
            if emp and emp.active:
                await state.clear()
                await message.answer(f"Ты уже в команде как {emp.name}.")
                return
            if emp:
                emp.name = name
                emp.active = False
                emp.role = "manager"
            else:
                emp = Employee(telegram_id=tid, name=name, role="manager", active=False)
                session.add(emp)
            await session.commit()

        await state.clear()
        await message.answer(
            f"Ок, {name}. Отправил заявку владельцу — как подтвердит, напишу сюда."
        )
        try:
            await message.bot.send_message(
                int(settings.owner_telegram_id),
                "👤 Новая заявка в команду\n\n"
                f"Имя: <b>{name}</b>\n"
                f"Telegram: {uname}\n"
                f"id: <code>{tid}</code>\n\n"
                "Добавить в CRM?",
                parse_mode="HTML",
                reply_markup=join_kb(tid),
            )
        except Exception:  # noqa: BLE001
            logger.exception("join notify owner failed tid=%s", tid)
            await message.answer(
                "Не смог достучаться до владельца. Скажи ему свой id:\n"
                f"<code>{tid}</code>",
                parse_mode="HTML",
            )

    @dp.callback_query(F.data.startswith("join:"))
    async def on_join_decision(callback: CallbackQuery) -> None:
        if not callback.from_user or not callback.data:
            return
        if int(callback.from_user.id) != int(settings.owner_telegram_id):
            await callback.answer("Только владелец.", show_alert=True)
            return
        parts = callback.data.split(":")
        if len(parts) != 3 or parts[1] not in {"ok", "no"} or not parts[2].isdigit():
            await callback.answer("Битая кнопка")
            return
        decision, tid = parts[1], int(parts[2])
        async with session_factory() as session:
            emp = await find_employee(session, tid)
            if not emp:
                await callback.answer("Заявки уже нет", show_alert=True)
                return
            if decision == "ok":
                emp.active = True
                emp.role = "manager"
                await session.commit()
                name = emp.name
                await callback.answer("Добавлен")
                if callback.message:
                    try:
                        await callback.message.edit_text(
                            f"✅ В команде: <b>{name}</b>\n"
                            f"id: <code>{tid}</code>\n"
                            f"Можно ставить задачи: /task {tid} | текст",
                            parse_mode="HTML",
                        )
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    await callback.bot.send_message(
                        tid,
                        f"✅ Тебя добавили в команду как <b>{name}</b>.\n"
                        "Жми /start — можно брать задачи.",
                        parse_mode="HTML",
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("join welcome failed tid=%s", tid)
            else:
                name = emp.name
                await session.delete(emp)
                await session.commit()
                await callback.answer("Отклонено")
                if callback.message:
                    try:
                        await callback.message.edit_text(f"✕ Отклонено: {name} ({tid})")
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    await callback.bot.send_message(
                        tid,
                        "Заявку в команду не приняли. Если это ошибка — напиши владельцу.",
                    )
                except Exception:  # noqa: BLE001
                    pass

    async def _author(session: AsyncSession, user: User | int) -> Employee | None:
        if isinstance(user, int):
            tid = int(user)
            if tid == int(settings.owner_telegram_id):
                return await ensure_owner(session, tid)
            emp = await find_employee(session, tid)
            return emp if emp and emp.active else None
        return await ensure_member(session, settings, user, create_if_missing=False)

    @dp.message(Command("todo"))
    async def cmd_todo(message: Message, command: CommandObject) -> None:
        title = (command.args or "").strip()
        if not title or not message.from_user:
            await message.answer("Формат: /todo Сделать отчёт")
            return
        async with session_factory() as session:
            author = await _author(session, message.from_user)
            if not author:
                await message.answer("Нет доступа.")
                return
            task, ok, err, clarify = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=author,
                author=author,
            )
            if clarify:
                await message.answer(clarify)
                return
        await _reply_created(message, ok, err, "Задача себе создана.")

    @dp.message(Command("boss"))
    async def cmd_boss(message: Message, command: CommandObject) -> None:
        title = (command.args or "").strip()
        if not title or not message.from_user:
            await message.answer("Формат: /boss Нужно согласовать закупку")
            return
        async with session_factory() as session:
            author = await _author(session, message.from_user)
            owner = await ensure_owner(session, settings.owner_telegram_id)
            if not author:
                await message.answer("Нет доступа.")
                return
            task, ok, err, clarify = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=owner,
                author=author,
            )
            if clarify:
                await message.answer(clarify)
                return
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
            author = await _author(session, message.from_user)
            assignee = await session.scalar(select(Employee).where(Employee.telegram_id == int(left)))
            if not author:
                await message.answer("Нет доступа.")
                return
            if not assignee:
                await message.answer("Человек не найден в CRM. Сначала /add_manager.")
                return
            task, ok, err, clarify = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=assignee,
                author=author,
            )
            if clarify:
                await message.answer(clarify)
                return
        await _reply_created(message, ok, err, f"Задача отправлена: {title}")

    @dp.message(Command("my"))
    async def cmd_my(message: Message) -> None:
        if not message.from_user:
            return
        async with session_factory() as session:
            emp = await _author(session, message.from_user)
            if not emp:
                await message.answer("Нет доступа.")
                return
            text = await format_open_tasks(session, assignee=emp)
        await message.answer(text)

    @dp.message(Command("team"))
    async def cmd_team(message: Message) -> None:
        if not message.from_user:
            return
        async with session_factory() as session:
            emp = await _author(session, message.from_user)
            if not emp:
                await message.answer("Нет доступа.")
                return
            people = (
                await session.scalars(select(Employee).where(Employee.active.is_(True)))
            ).all()
            text = await format_open_tasks(session, people=list(people))
        await message.answer(text)

    @dp.message(Command("name"))
    async def cmd_name(message: Message, command: CommandObject) -> None:
        new_name = (command.args or "").strip()
        if not new_name or not message.from_user:
            await message.answer("Формат: /name Ярослав")
            return
        async with session_factory() as session:
            emp = await _author(session, message.from_user)
            if not emp:
                await message.answer("Сначала /start")
                return
            emp.name = new_name[:200]
            await session.commit()
        await message.answer(f"Ок, в CRM ты теперь: {new_name}")

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
            emp = await find_employee(session, tid)
            if emp:
                emp.name = name
                if tid != int(settings.owner_telegram_id):
                    emp.role = "manager"
                else:
                    emp.role = "owner"
                emp.active = True
            else:
                role = "owner" if tid == int(settings.owner_telegram_id) else "manager"
                session.add(Employee(telegram_id=tid, name=name, role=role))
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
            task, ok, err, clarify = await create_and_notify(
                session=session,
                bot=message.bot,
                settings=settings,
                title=title,
                assignee=emp,
                author=author,
            )
            if clarify:
                await message.answer(clarify)
                return
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
            task, ok, err, clarify = await create_and_notify(
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
            if clarify:
                await message.answer(clarify)
                return
        await message.answer(f"Еженедельная задача создана: {title}")

    def _task_allowed_ids(task: Task) -> set[int]:
        allowed = {int(settings.owner_telegram_id)}
        if task.assignee and task.assignee.telegram_id is not None:
            allowed.add(int(task.assignee.telegram_id))
        for link in task.assignees or []:
            if link.employee and link.employee.telegram_id is not None:
                allowed.add(int(link.employee.telegram_id))
        return allowed

    @dp.callback_query(F.data.startswith("doing:") | F.data.startswith("done:"))
    async def on_task_status(callback: CallbackQuery) -> None:
        if not callback.data or not callback.from_user:
            return
        parts = callback.data.split(":")
        action = parts[0]
        if action not in {"doing", "done"}:
            return
        try:
            run_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            task_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        except ValueError:
            await callback.answer("Битая кнопка", show_alert=True)
            return

        notify_ids: set[int] = set()
        name = "?"
        title = ""
        new_status = action
        uid = int(callback.from_user.id)
        async with session_factory() as session:
            run = await resolve_run(session, run_id=run_id, task_id=task_id)
            if not run or not run.task:
                logger.warning(
                    "status miss data=%s run_id=%s task_id=%s",
                    callback.data,
                    run_id,
                    task_id,
                )
                await callback.answer(
                    "Задача не найдена. Создай новую — старые кнопки могли протухнуть после деплоя.",
                    show_alert=True,
                )
                return
            if uid not in _task_allowed_ids(run.task):
                await callback.answer("Не твоя задача", show_alert=True)
                return
            from app.tasks_service import apply_status

            actor = await find_employee(session, uid)
            await apply_status(
                session,
                run.task,
                new_status,
                actor_id=actor.id if actor else None,
            )
            if new_status == "done":
                run.status = "done"
                run.completed_at = datetime.utcnow()
            await session.commit()
            name = (
                next(
                    (
                        a.employee.name
                        for a in (run.task.assignees or [])
                        if a.employee and int(a.employee.telegram_id or 0) == uid
                    ),
                    None,
                )
                or (run.task.assignee.name if run.task.assignee else "?")
            )
            title = run.task.title
            run_id_final = int(run.id)
            task_id_final = int(run.task.id)
            notify_ids.add(int(settings.owner_telegram_id))
            if run.task.created_by and run.task.created_by.telegram_id is not None:
                notify_ids.add(int(run.task.created_by.telegram_id))

        if new_status == "doing":
            await callback.answer("В работе 🔵")
            if callback.message:
                try:
                    await callback.message.edit_text(
                        f"🔵 В работе: <b>{title}</b>\n\nЖми «Сделано», когда закончишь.",
                        parse_mode="HTML",
                        reply_markup=task_action_kb(
                            run_id_final, task_id_final, status="doing"
                        ),
                    )
                except Exception:  # noqa: BLE001
                    pass
            for tid in notify_ids:
                if tid == uid:
                    continue
                try:
                    await callback.bot.send_message(
                        tid, f"🔵 {name} взял(а) в работу: {title}"
                    )
                except Exception:  # noqa: BLE001
                    pass
            return

        await callback.answer("Готово ✅")
        if callback.message:
            try:
                await callback.message.edit_text(f"✅ Сделано: {title}")
            except Exception:  # noqa: BLE001
                pass
        for tid in notify_ids:
            if tid == uid:
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

    def _is_all_token(token: str) -> bool:
        t = (token or "").strip().lower()
        return t in {
            "all",
            "team",
            "всем",
            "всех",
            "все",
            "команде",
            "команда",
            "everyone",
            "на всех",
            "для всех",
        }

    def _resolve_assignees(
        people: list[Employee], token: str, author: Employee, *, raw_text: str = ""
    ) -> list[Employee] | None:
        blob = f"{token} {raw_text}".lower()
        if _is_all_token(token) or re.search(
            r"(?i)(?<![а-яa-z])(всем|всех|на\s+всех|для\s+всех|всей\s+команде|команде)(?![а-яa-z])",
            blob,
        ):
            return list(people) if people else None
        one = _match_assignee(people, token, author)
        return [one] if one else None

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
                author = await _author(session, message.from_user)
                if not author:
                    await wait.edit_text(
                        "Не удалось войти в команду. Нажми /start.\n"
                        f"Твой id: {message.from_user.id}"
                    )
                    return
                people = (
                    await session.scalars(select(Employee).where(Employee.active.is_(True)))
                ).all()
                from app.nlp import parse_intent

                is_owner = message.from_user.id == settings.owner_telegram_id
                # быстрый путь без LLM: «поставь задачу всем …»
                m_all = re.search(
                    r"(?i)^\s*(?:поставь|назначь|создай)?\s*"
                    r"(?:задач[ауе]?\s+)?"
                    r"(?:всем|на\s+всех|для\s+всех|всей\s+команде)\s*[:\-]?\s*(.+)$",
                    text.strip(),
                )
                if m_all and m_all.group(1).strip():
                    intent = {
                        "action": "create_task",
                        "title": m_all.group(1).strip(),
                        "assignee": "all",
                        "due": "default",
                    }
                else:
                    intent = await parse_intent(
                        settings,
                        text=text,
                        author_name=author.name,
                        people=[{"name": p.name, "role": p.role} for p in people],
                        is_owner=is_owner,
                    )
                action = intent.get("action")
                if action == "create_task":
                    title = str(intent.get("title") or "").strip()
                    token = str(intent.get("assignee") or "me")
                    if not title:
                        # иногда модель кладёт всё в assignee — вытащим из исходного текста
                        m = re.search(
                            r"(?i)(?:задач[ау]|поставь|назначь)\s+(.+)$", text.strip()
                        )
                        title = (m.group(1) if m else text).strip()
                        title = re.sub(
                            r"(?i)\b(всем|всех|на\s+всех|для\s+всех|команде)\b",
                            "",
                            title,
                        ).strip(" .,!—-")
                    if not title:
                        await wait.edit_text("Не увидел текст задачи. Сформулируй ещё раз.")
                        return
                    # «всем» часто теряется в tool — дублируем эвристикой по исходному тексту
                    if re.search(
                        r"(?i)(?<![а-яa-z])(всем|всех|на\s+всех|для\s+всех|всей\s+команде)(?![а-яa-z])",
                        text,
                    ):
                        token = "all"
                    targets = _resolve_assignees(
                        list(people), token, author, raw_text=text
                    )
                    if not targets:
                        await wait.edit_text(
                            f"Не понял, кому задача («{token}»). "
                            "Назови имя, «себе», «боссу» или «всем»."
                        )
                        return
                    due_hint = str(intent.get("due") or "default")
                    task, ok, err, clarify = await create_and_notify(
                        session=session,
                        bot=message.bot,
                        settings=settings,
                        title=title,
                        assignees=targets,
                        author=author,
                        due_hint=due_hint,
                    )
                    due_txt = (
                        task.due_date.strftime("%d.%m.%Y")
                        if task and task.due_date
                        else "—"
                    )
                    if len(targets) == 1:
                        who = targets[0].name
                    else:
                        who = f"всем ({len(targets)} чел.)"
                    text = f"Готово: задача для {who}\n«{title}»\nСрок: {due_txt}"
                    if not ok:
                        text += f"\n\n⚠️ В Telegram не ушло: {err or 'неизвестно'}"
                    await wait.edit_text(text)
                    return
                if action in {"list_my_tasks", "list_tasks"}:
                    who = str(intent.get("who") or "me").strip()
                    if action == "list_my_tasks":
                        who = "me"
                    who_l = who.lower()
                    if who_l in {"all", "team", "все", "команда", "всех", "у всех", "статус"}:
                        report = await format_open_tasks(session, people=list(people))
                        await wait.edit_text(report)
                        return
                    if who_l in {"me", "себе", "мне", "я", "мои"}:
                        report = await format_open_tasks(session, assignee=author)
                        await wait.edit_text(report)
                        return
                    person = _match_assignee(list(people), who, author)
                    if not person:
                        await wait.edit_text(
                            f"Не нашёл «{who}» в команде. Спроси «у кого какие задачи» или назови имя точно."
                        )
                        return
                    report = await format_open_tasks(session, assignee=person)
                    await wait.edit_text(report)
                    return
                if action in {"edit_task", "delete_task"}:
                    query = str(intent.get("query") or "").strip()
                    who = str(intent.get("who") or ("all" if is_owner else "me")).strip()
                    if not query:
                        await wait.edit_text("Укажи id или часть названия задачи.")
                        return
                    who_l = who.lower()
                    q = select(Task).where(Task.active.is_(True), Task.status != "done")
                    if who_l in {"me", "себе", "мне", "я", "мои"}:
                        q = q.where(Task.assignee_id == author.id)
                    elif who_l not in {"all", "team", "все", "команда", "всех"}:
                        scope_emp = _match_assignee(list(people), who, author)
                        if not scope_emp:
                            await wait.edit_text(f"Не нашёл человека «{who}».")
                            return
                        q = q.where(Task.assignee_id == scope_emp.id)
                    elif not is_owner:
                        q = q.where(Task.assignee_id == author.id)
                    tasks = (await session.scalars(q.order_by(Task.id))).all()
                    match: Task | None = None
                    if query.isdigit():
                        match = next((t for t in tasks if t.id == int(query)), None)
                    if not match:
                        ql = query.lower()
                        cands = [t for t in tasks if ql in t.title.lower()]
                        if len(cands) == 1:
                            match = cands[0]
                        elif len(cands) > 1:
                            lines = [f"#{t.id} {t.title}" for t in cands[:8]]
                            await wait.edit_text(
                                "Нашёл несколько задач, уточни номером:\n" + "\n".join(lines)
                            )
                            return
                    if not match:
                        await wait.edit_text(f"Не нашёл задачу «{query}».")
                        return
                    if action == "delete_task":
                        match.active = False
                        await session.commit()
                        await wait.edit_text(f"Удалил #{match.id}: {match.title}")
                        return
                    new_title = str(intent.get("title") or "").strip()
                    if not new_title:
                        await wait.edit_text("Какой новый текст задачи?")
                        return
                    old = match.title
                    match.title = new_title
                    await session.commit()
                    await wait.edit_text(f"Обновил #{match.id}:\nбыло: {old}\nстало: {new_title}")
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

    @dp.message(F.text, ~StateFilter(JoinForm.waiting_name))
    async def on_text(message: Message) -> None:
        if not message.text or message.text.startswith("/"):
            return
        await _handle_natural(message, message.text)

    return bot, dp
