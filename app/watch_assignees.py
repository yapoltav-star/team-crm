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

STOCK_HOW_IT_WORKS = (
    "Раз в выбранные дни бот смотрит остатки на «нашем складе» в WB Dashboard. "
    "Если по артикулу (или семье артикулов) на складе пусто или почти пусто, "
    "но товар всё ещё продаётся (есть заказы/выкупы), создаётся задача "
    "«Закупить …, на вашем складе кончился». "
    "Одна и та же позиция не дублируется чаще, чем раз в период кулдауна. "
    "Ниже можно выбрать, кому эти задачи ставить по умолчанию."
)

SHELF_HOW_IT_WORKS = (
    "Раз в выбранные дни бот проверяет полки «Смотрите также» у наших карточек "
    "с продажами. В топ-15 соседних товаров считает, какая доля наших "
    "(бренд PVS / свои nm). Если доля ниже порога (например ниже 60%), "
    "создаётся задача «Полка слабая…» — нужно усилить присутствие на полке. "
    "Артикулы из исключений не проверяются. "
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
