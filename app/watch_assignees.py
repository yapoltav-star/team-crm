"""Кто получает автозадачи склада / полок + тексты «как это работает»."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AppSetting, Employee

logger = logging.getLogger(__name__)

KEY_STOCK_ASSIGNEE = "stock_assignee_id"
KEY_SHELF_ASSIGNEE = "shelf_assignee_id"
KEY_STOCK_PAUSED = "stock_watch_paused"
KEY_SHELF_PAUSED = "shelf_watch_paused"
KEY_SHELF_EXCLUDE = "shelf_watch_exclude"
KEY_STOCK_DAYS = "stock_watch_days"
KEY_STOCK_TIME = "stock_watch_time"
KEY_STOCK_COMMENT = "stock_watch_comment"
KEY_SHELF_DAYS = "shelf_watch_days"
KEY_SHELF_TIME = "shelf_watch_time"
KEY_SHELF_COMMENT = "shelf_watch_comment"

_TRUTHY = {"1", "true", "yes", "on", "y"}
_VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

STOCK_HOW_IT_WORKS = (
    "Раз в выбранные дни бот смотрит остатки на «нашем складе» в WB Dashboard. "
    "Если по артикулу (или семье артикулов) на складе пусто или почти пусто, "
    "но товар всё ещё продаётся (есть заказы/выкупы), создаётся задача "
    "«Закупить …, на вашем складе кончился». "
    "Артикулы из активных наборов «по артикулам» сюда не попадают — уходят своему человеку. "
    "Одна и та же позиция не дублируется чаще, чем раз в период кулдауна. "
    "Ниже можно выбрать, кому ставить остальные задачи по умолчанию."
)

SHELF_HOW_IT_WORKS = (
    "Раз в выбранные дни бот проверяет полки «Смотрите также» у наших карточек "
    "с продажами. В топ-15 соседних товаров считает, какая доля наших "
    "(бренд PVS / свои nm). Если доля ниже порога (например ниже 60%), "
    "создаётся задача «Полка слабая…» — нужно усилить присутствие на полке. "
    "Ненужные артикулы можно снять в таблице (кнопка «Артикулы»). "
    "Повтор по тому же nm не чаще кулдауна. "
    "Ниже — кому ставить такие задачи по умолчанию."
)


async def get_setting(session: AsyncSession, key: str) -> str:
    row = await session.get(AppSetting, key)
    return (row.value if row else "") or ""


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value or "", updated_at=datetime.utcnow())
        session.add(row)
    else:
        row.value = value or ""
        row.updated_at = datetime.utcnow()


async def get_assignee_id_setting(session: AsyncSession, key: str) -> int | None:
    raw = (await get_setting(session, key)).strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n > 0 else None


async def set_assignee_id_setting(
    session: AsyncSession, key: str, employee_id: int | None
) -> None:
    if employee_id is None or int(employee_id) <= 0:
        await set_setting(session, key, "")
    else:
        await set_setting(session, key, str(int(employee_id)))


async def is_watch_paused(session: AsyncSession, key: str) -> bool:
    return (await get_setting(session, key)).strip().lower() in _TRUTHY


async def set_watch_paused(session: AsyncSession, key: str, paused: bool) -> None:
    await set_setting(session, key, "1" if paused else "")


def _normalize_vendor_list(codes: list | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        vc = str(raw or "").strip()
        if not vc:
            continue
        key = vc.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(vc)
    out.sort(key=lambda x: x.casefold())
    return out


async def load_shelf_exclude_codes(session: AsyncSession) -> list[str]:
    """Исключения из UI (дополнительно к SHELF_EXCLUDE_VENDOR_CODES в env)."""
    import json

    raw = (await get_setting(session, KEY_SHELF_EXCLUDE)).strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = [x.strip() for x in raw.split(",") if x.strip()]
    if not isinstance(data, list):
        return []
    return _normalize_vendor_list(data)


async def save_shelf_exclude_codes(session: AsyncSession, codes: list[str] | None) -> list[str]:
    import json

    clean = _normalize_vendor_list(codes)
    await set_setting(session, KEY_SHELF_EXCLUDE, json.dumps(clean, ensure_ascii=False))
    return clean


async def effective_shelf_exclude_set(
    session: AsyncSession, settings: Settings
) -> set[str]:
    env = set(settings.shelf_exclude_set)
    ui = {c.casefold() for c in await load_shelf_exclude_codes(session)}
    return env | ui


def normalize_watch_days(raw: str | None, fallback: str) -> str:
    parts = []
    seen: set[str] = set()
    for chunk in (raw or "").replace(";", ",").split(","):
        d = chunk.strip().lower()[:3]
        if d not in _VALID_DAYS or d in seen:
            continue
        seen.add(d)
        parts.append(d)
    if not parts:
        for chunk in (fallback or "").replace(";", ",").split(","):
            d = chunk.strip().lower()[:3]
            if d in _VALID_DAYS and d not in seen:
                seen.add(d)
                parts.append(d)
    if not parts:
        parts = ["mon", "wed", "fri"]
    parts.sort(key=lambda x: _DAY_ORDER.index(x))
    return ",".join(parts)


def normalize_watch_time(raw: str | None, fallback: str) -> str:
    text = (raw or "").strip() or (fallback or "").strip() or "09:00"
    try:
        hh_s, mm_s = text.split(":")[:2]
        hh, mm = int(hh_s), int(mm_s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("range")
        return f"{hh:02d}:{mm:02d}"
    except Exception:
        try:
            hh_s, mm_s = (fallback or "09:00").split(":")[:2]
            return f"{int(hh_s):02d}:{int(mm_s):02d}"
        except Exception:
            return "09:00"


async def get_watch_schedule(
    session: AsyncSession,
    settings: Settings,
    *,
    kind: str,
) -> dict[str, str]:
    """kind: stock | shelf → days, time, comment (DB override или env)."""
    if kind == "shelf":
        days_fb = settings.shelf_watch_days or "tue,thu"
        time_fb = settings.shelf_watch_time or "10:00"
        days_key, time_key, comment_key = KEY_SHELF_DAYS, KEY_SHELF_TIME, KEY_SHELF_COMMENT
    else:
        days_fb = settings.stock_watch_days or "mon,wed,fri"
        time_fb = settings.stock_watch_time or "09:00"
        days_key, time_key, comment_key = KEY_STOCK_DAYS, KEY_STOCK_TIME, KEY_STOCK_COMMENT
    days_raw = (await get_setting(session, days_key)).strip() or days_fb
    time_raw = (await get_setting(session, time_key)).strip() or time_fb
    comment = (await get_setting(session, comment_key)).strip()
    return {
        "days": normalize_watch_days(days_raw, days_fb),
        "time": normalize_watch_time(time_raw, time_fb),
        "comment": comment[:1000],
    }


async def save_watch_schedule(
    session: AsyncSession,
    settings: Settings,
    *,
    kind: str,
    days: str | None = None,
    time: str | None = None,
    comment: str | None = None,
) -> dict[str, str]:
    if kind == "shelf":
        days_fb = settings.shelf_watch_days or "tue,thu"
        time_fb = settings.shelf_watch_time or "10:00"
        days_key, time_key, comment_key = KEY_SHELF_DAYS, KEY_SHELF_TIME, KEY_SHELF_COMMENT
    else:
        days_fb = settings.stock_watch_days or "mon,wed,fri"
        time_fb = settings.stock_watch_time or "09:00"
        days_key, time_key, comment_key = KEY_STOCK_DAYS, KEY_STOCK_TIME, KEY_STOCK_COMMENT
    if days is not None:
        await set_setting(session, days_key, normalize_watch_days(days, days_fb))
    if time is not None:
        await set_setting(session, time_key, normalize_watch_time(time, time_fb))
    if comment is not None:
        await set_setting(session, comment_key, str(comment).strip()[:1000])
    return await get_watch_schedule(session, settings, kind=kind)


def reschedule_watch_job(scheduler, settings: Settings, *, kind: str, days: str, time: str) -> None:
    """Обновить cron у APScheduler (если job есть)."""
    if scheduler is None:
        return
    job_id = "shelf_watch" if kind == "shelf" else "stock_watch"
    try:
        hh, mm = [int(x) for x in normalize_watch_time(time, "09:00").split(":")[:2]]
    except Exception:
        hh, mm = (10, 0) if kind == "shelf" else (9, 0)
    days_norm = normalize_watch_days(
        days,
        (settings.shelf_watch_days if kind == "shelf" else settings.stock_watch_days) or "mon",
    )
    try:
        from apscheduler.triggers.cron import CronTrigger

        job = scheduler.get_job(job_id)
        if not job:
            return
        scheduler.reschedule_job(
            job_id,
            trigger=CronTrigger(
                day_of_week=days_norm,
                hour=hh,
                minute=mm,
                timezone=settings.tz_name,
            ),
        )
        logger.info("rescheduled %s → %s @ %02d:%02d", job_id, days_norm, hh, mm)
    except Exception:
        logger.exception("reschedule %s failed", job_id)


async def _emp_by_id(session: AsyncSession, emp_id: int | None) -> Employee | None:
    if not emp_id:
        return None
    emp = await session.get(Employee, int(emp_id))
    if emp and emp.active:
        return emp
    return None


async def resolve_stock_assignee(
    session: AsyncSession,
    settings: Settings,
    owner: Employee,
) -> Employee:
    """DB override → telegram id → имя → владелец."""
    db_id = await get_assignee_id_setting(session, KEY_STOCK_ASSIGNEE)
    emp = await _emp_by_id(session, db_id)
    if emp:
        return emp

    if settings.stock_assignee_telegram_id:
        emp = await session.scalar(
            select(Employee).where(
                Employee.telegram_id == int(settings.stock_assignee_telegram_id),
                Employee.active.is_(True),
            )
        )
        if emp:
            return emp
        logger.warning(
            "stock assignee telegram_id=%s not found",
            settings.stock_assignee_telegram_id,
        )

    needle = (settings.stock_assignee_name or "").strip()
    if needle:
        emp = await session.scalar(
            select(Employee).where(
                Employee.active.is_(True),
                Employee.role != "owner",
                Employee.name.ilike(f"%{needle}%"),
            )
        )
        if emp:
            return emp
        logger.warning("stock assignee name=%r not found — owner", needle)

    return owner


async def resolve_shelf_assignee(
    session: AsyncSession,
    settings: Settings,
    owner: Employee,
) -> Employee:
    """DB override → telegram id → владелец."""
    db_id = await get_assignee_id_setting(session, KEY_SHELF_ASSIGNEE)
    emp = await _emp_by_id(session, db_id)
    if emp:
        return emp

    if settings.shelf_assignee_telegram_id:
        emp = await session.scalar(
            select(Employee).where(
                Employee.telegram_id == int(settings.shelf_assignee_telegram_id),
                Employee.active.is_(True),
            )
        )
        if emp:
            return emp
        logger.warning(
            "shelf assignee telegram_id=%s not found",
            settings.shelf_assignee_telegram_id,
        )

    return owner
