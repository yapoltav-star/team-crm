"""Автозадачи по остаткам на НАШЕМ складе (WB Dashboard → own-warehouse).

Склады WB (поставки по регионам) — отдельная большая тема, пока выключены.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Employee, Task, TaskAssignee
from app.notify import notify_task_assignee
from app.tasks_service import add_event, set_assignees

logger = logging.getLogger("stock-watch")

MARKER_PREFIX = "[auto:own-stock:"


@dataclass
class OwnCritical:
    vendor_code: str
    name: str
    stock: int
    family_stock: int
    family: list[str]
    ordered: int
    buyouts: int
    family_key: str


def _marker(family_key: str) -> str:
    """Короткий маркер для кулдауна — без длинного списка артикулов в тексте задачи."""
    digest = hashlib.sha1(family_key.encode("utf-8")).hexdigest()[:12]
    return f"{MARKER_PREFIX}{digest}]"


def _sales_by_vendor(supply_report: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in supply_report or []:
        vc = str(r.get("vendor_code") or "").strip()
        if not vc:
            continue
        a = out.setdefault(vc, {"ordered": 0, "buyouts": 0})
        a["ordered"] += int(r.get("ordered_qty") or 0)
        a["buyouts"] += int(r.get("buyout_qty") or 0)
    return out


def analyze_own_warehouse(
    own_payload: dict[str, Any],
    dash_payload: dict[str, Any],
    *,
    min_orders: int = 5,
    require_buyouts: bool = True,
    max_family_stock: int = 0,
) -> list[OwnCritical]:
    """Критично: на нашем складе мало/пусто, но по артикулу есть продажи."""
    sales = _sales_by_vendor(dash_payload.get("supply_report") or [])
    by_vendor = own_payload.get("by_vendor") or {}
    rows = own_payload.get("rows") or []
    name_by_vc = {
        str(r.get("vendor_code") or "").strip(): str(r.get("name") or r.get("model_name") or "")
        for r in rows
        if r.get("vendor_code")
    }

    # одна задача на семью артикулов (общий остаток)
    best: dict[str, OwnCritical] = {}
    for vc, meta in by_vendor.items():
        vc = str(vc or "").strip()
        if not vc:
            continue
        sal = sales.get(vc) or {"ordered": 0, "buyouts": 0}
        ordered = int(sal["ordered"])
        buyouts = int(sal["buyouts"])
        if ordered < max(1, min_orders):
            continue
        if require_buyouts and buyouts < 1:
            continue

        stock = int(meta.get("stock") or 0)
        family_stock = meta.get("family_stock")
        if family_stock is None:
            family_stock = stock
        family_stock = int(family_stock or 0)
        if family_stock > max_family_stock:
            continue

        family = [str(x) for x in (meta.get("family") or [vc]) if x]
        if vc not in family:
            family = [vc, *family]
        family_key = "|".join(sorted(set(family)))
        # суммарные продажи по семье — чтобы выбрать «главный» артикул
        fam_orders = sum(int((sales.get(m) or {}).get("ordered") or 0) for m in family)
        fam_buy = sum(int((sales.get(m) or {}).get("buyouts") or 0) for m in family)
        item = OwnCritical(
            vendor_code=vc,
            name=name_by_vc.get(vc) or "",
            stock=stock,
            family_stock=family_stock,
            family=sorted(set(family)),
            ordered=fam_orders or ordered,
            buyouts=fam_buy or buyouts,
            family_key=family_key,
        )
        prev = best.get(family_key)
        if prev is None or item.ordered > prev.ordered:
            best[family_key] = item

    critical = list(best.values())
    critical.sort(key=lambda x: (x.family_stock, -x.ordered, x.vendor_code))
    return critical


async def fetch_json(url: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"expected object from {url}")
            return data


async def _blocked_markers(session: AsyncSession, *, cooldown_days: int) -> set[str]:
    """Не создавать снова: открытые задачи или любые с маркером за cooldown_days."""
    cutoff = datetime.utcnow() - timedelta(days=max(1, cooldown_days))
    tasks = (
        await session.scalars(select(Task).where(Task.active.is_(True)))
    ).all()
    out: set[str] = set()
    for t in tasks:
        blob = f"{t.description or ''}\n{t.articles or ''}\n{t.title or ''}"
        if MARKER_PREFIX not in blob:
            continue
        start = blob.find(MARKER_PREFIX)
        end = blob.find("]", start)
        if end <= start:
            continue
        marker = blob[start : end + 1]
        if t.status != "done":
            out.add(marker)
            continue
        created = t.created_at or datetime.utcnow()
        if created >= cutoff:
            out.add(marker)
    return out


async def run_stock_watch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    bot=None,
) -> dict[str, Any]:
    if not settings.stock_watch_enabled:
        return {"ok": False, "skipped": "disabled"}
    if not settings.wb_dashboard_url:
        return {"ok": False, "error": "WB_DASHBOARD_URL пуст"}

    base = settings.wb_dashboard_url.rstrip("/")
    try:
        own = await fetch_json(f"{base}/api/own-warehouse-stock")
        dash = await fetch_json(f"{base}/api/dashboard-data")
    except Exception as exc:  # noqa: BLE001
        logger.exception("dashboard fetch failed")
        return {"ok": False, "error": f"dashboard: {exc}"}

    if own.get("error"):
        return {"ok": False, "error": f"own-warehouse: {own.get('error')}"}

    critical = analyze_own_warehouse(
        own,
        dash,
        min_orders=settings.stock_min_orders,
        require_buyouts=settings.stock_require_buyouts,
        max_family_stock=settings.stock_own_max_stock,
    )
    top = critical[: max(1, settings.stock_max_tasks)]

    created: list[dict[str, Any]] = []
    skipped_existing = 0

    async with session_factory() as session:
        owner = await session.scalar(
            select(Employee).where(
                Employee.telegram_id == int(settings.owner_telegram_id)
            )
        )
        if not owner:
            owner = await session.scalar(
                select(Employee).where(Employee.role == "owner", Employee.active.is_(True))
            )
        if not owner:
            return {"ok": False, "error": "владелец не найден в CRM"}

        assignee = owner
        if settings.stock_assignee_telegram_id:
            emp = await session.scalar(
                select(Employee).where(
                    Employee.telegram_id == int(settings.stock_assignee_telegram_id),
                    Employee.active.is_(True),
                )
            )
            if emp:
                assignee = emp

        existing = await _blocked_markers(
            session, cooldown_days=settings.stock_cooldown_days
        )
        today = datetime.now(settings.tz).date()
        skipped_cooldown = 0

        for sku in top:
            marker = _marker(sku.family_key)
            if marker in existing:
                skipped_cooldown += 1
                continue

            title = f'Закупить {sku.vendor_code}, на вашем складе кончился'
            # маркер только для кулдауна, в UI описание не показываем
            desc = _marker(sku.family_key)
            task = Task(
                title=title[:500],
                description=desc,
                articles=(sku.vendor_code[:500]),
                assignee_id=assignee.id,
                created_by_id=owner.id,
                status="todo",
                kind="once",
                notify_time=datetime.now(settings.tz).strftime("%H:%M"),
                due_date=today + timedelta(days=1),
                priority="high" if sku.family_stock <= 0 else "normal",
                created_at=datetime.utcnow(),
            )
            session.add(task)
            await session.flush()
            await set_assignees(
                session, task, [assignee.id], actor_id=owner.id, log=True
            )
            await add_event(
                session,
                task.id,
                f"Авто: наш склад — {sku.vendor_code}",
                kind="created",
                actor_id=owner.id,
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
            notified, nerr = await notify_task_assignee(
                bot=bot,
                session=session,
                task=task,
                due=task.due_date or today,
                employees=[assignee],
            )
            created.append(
                {
                    "id": task.id,
                    "vendor_code": sku.vendor_code,
                    "family_stock": sku.family_stock,
                    "ordered": sku.ordered,
                    "notified": notified,
                    "notify_error": nerr,
                }
            )
            existing.add(marker)

        if created and bot:
            lines = [
                f"🏭 <b>Наш склад</b>: новые задачи <b>{len(created)}</b> "
                f"(критично всего {len(critical)}, пропущено по кулдауну {skipped_cooldown})",
                f"Срез: {own.get('as_of') or '—'}",
                "",
                "Создано:",
            ]
            for row in created[:10]:
                lines.append(
                    f"• <code>{row['vendor_code']}</code> — "
                    f"склад {row['family_stock']} шт, заказы {row['ordered']}"
                )
            try:
                await bot.send_message(
                    int(settings.owner_telegram_id),
                    "\n".join(lines),
                    parse_mode="HTML",
                )
            except Exception:  # noqa: BLE001
                logger.exception("own-stock digest notify failed")

    return {
        "ok": True,
        "mode": "own_warehouse",
        "as_of": own.get("as_of"),
        "critical_total": len(critical),
        "created": created,
        "skipped_existing": skipped_cooldown,
        "cooldown_days": settings.stock_cooldown_days,
    }
