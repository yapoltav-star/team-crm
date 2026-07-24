"""Автозадачи по критичным остаткам из WB Dashboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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

MARKER_PREFIX = "[auto:stock:"


@dataclass
class CriticalSku:
    vendor_code: str
    nm_id: int | None
    min_days: float
    recommend: int
    warehouses: int
    ordered: int
    buyouts: int


def _marker(vendor_code: str) -> str:
    return f"{MARKER_PREFIX}{vendor_code}]"


def analyze_supply(
    payload: dict[str, Any],
    *,
    target_days: int | None = None,
    min_recommend: int = 5,
    min_orders: int = 5,
    require_buyouts: bool = True,
) -> tuple[int, list[CriticalSku]]:
    """Критичные остатки только по артикулам с продажами (заказы/выкупы)."""
    settings = payload.get("settings") or {}
    target = int(target_days or settings.get("target_coverage_days") or 30)
    rows = payload.get("supply_report") or []

    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        vc = str(r.get("vendor_code") or r.get("nm_id") or "").strip()
        if not vc:
            continue
        if vc not in by:
            by[vc] = {
                "nm_id": r.get("nm_id"),
                "planned": 0,
                "raw_recommend": 0,
                "min_days": None,
                "wh": 0,
                "ordered": 0,
                "buyouts": 0,
            }
        if r.get("planned_supply_qty"):
            by[vc]["planned"] = int(r["planned_supply_qty"] or 0)
        period = int(r.get("period_days") or 0)
        ordered = int(r.get("ordered_qty") or 0)
        buyout = int(r.get("buyout_qty") or 0)
        stock = int(r.get("current_stock") or 0)
        by[vc]["ordered"] += ordered
        by[vc]["buyouts"] += buyout
        # скорость только там, где реально были заказы
        if ordered <= 0 or period <= 0:
            by[vc]["wh"] += 1
            continue
        daily = ordered / period
        days = stock / daily
        rec = max(0, round(daily * target - stock))
        by[vc]["raw_recommend"] += rec
        by[vc]["wh"] += 1
        prev = by[vc]["min_days"]
        by[vc]["min_days"] = days if prev is None else min(prev, days)

    critical: list[CriticalSku] = []
    for vc, a in by.items():
        ordered_total = int(a["ordered"] or 0)
        buyout_total = int(a["buyouts"] or 0)
        # без продаж / заказов — не трогаем
        if ordered_total < max(1, min_orders):
            continue
        if require_buyouts and buyout_total < 1:
            continue
        total = max(0, int(a["raw_recommend"]) - int(a["planned"] or 0))
        min_days = a["min_days"]
        if total < min_recommend:
            continue
        if min_days is None or min_days >= target:
            continue
        critical.append(
            CriticalSku(
                vendor_code=vc,
                nm_id=int(a["nm_id"]) if a.get("nm_id") else None,
                min_days=float(min_days),
                recommend=total,
                warehouses=int(a["wh"]),
                ordered=ordered_total,
                buyouts=buyout_total,
            )
        )
    critical.sort(key=lambda x: (x.min_days, -x.recommend, -x.ordered))
    return target, critical


async def fetch_dashboard(url: str) -> dict[str, Any]:
    base = url.rstrip("/")
    endpoint = f"{base}/api/dashboard-data"
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(endpoint) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _open_stock_markers(session: AsyncSession) -> set[str]:
    tasks = (
        await session.scalars(
            select(Task).where(Task.active.is_(True), Task.status != "done")
        )
    ).all()
    out: set[str] = set()
    for t in tasks:
        desc = t.description or ""
        arts = t.articles or ""
        blob = f"{desc}\n{arts}"
        if MARKER_PREFIX not in blob:
            continue
        # вытащим vendor из маркера
        start = blob.find(MARKER_PREFIX)
        end = blob.find("]", start)
        if end > start:
            out.add(blob[start : end + 1])
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

    try:
        payload = await fetch_dashboard(settings.wb_dashboard_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dashboard fetch failed")
        return {"ok": False, "error": f"dashboard: {exc}"}

    target, critical = analyze_supply(
        payload,
        target_days=settings.stock_target_days or None,
        min_recommend=settings.stock_min_recommend,
        min_orders=settings.stock_min_orders,
        require_buyouts=settings.stock_require_buyouts,
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

        existing = await _open_stock_markers(session)
        today = datetime.now(settings.tz).date()

        for sku in top:
            marker = _marker(sku.vendor_code)
            if marker in existing:
                skipped_existing += 1
                continue
            title = (
                f"Остатки: дозаказать {sku.vendor_code} "
                f"(~{sku.recommend} шт, ~{sku.min_days:.0f} дн.)"
            )
            desc = (
                f"{marker}\n"
                f"Автозадача из WB Dashboard.\n"
                f"Артикул: {sku.vendor_code}\n"
                f"nm_id: {sku.nm_id or '—'}\n"
                f"Заказы за период: {sku.ordered}, выкупы: {sku.buyouts}\n"
                f"Мин. покрытие по складам: ~{sku.min_days:.1f} дн. "
                f"(цель {target} дн.)\n"
                f"Рекомендуется поставить: ~{sku.recommend} шт.\n"
                f"Складов в отчёте: {sku.warehouses}\n"
                f"Источник: {settings.wb_dashboard_url.rstrip('/')}/"
            )
            task = Task(
                title=title[:500],
                description=desc,
                articles=sku.vendor_code[:500],
                assignee_id=assignee.id,
                created_by_id=owner.id,
                status="todo",
                kind="once",
                notify_time=datetime.now(settings.tz).strftime("%H:%M"),
                due_date=today + timedelta(days=1),
                priority="high" if sku.min_days < 3 else "normal",
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
                f"Авто: критичные остатки — {sku.vendor_code}",
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
                    "recommend": sku.recommend,
                    "min_days": round(sku.min_days, 1),
                    "notified": notified,
                    "notify_error": nerr,
                }
            )
            existing.add(marker)

        # сводка владельцу, если что-то нашли
        if critical and bot:
            lines = [
                f"📦 Остатки WB: критично <b>{len(critical)}</b> арт. "
                f"с продажами (заказы ≥{settings.stock_min_orders}"
                f"{', есть выкупы' if settings.stock_require_buyouts else ''}; "
                f"поставить ≥{settings.stock_min_recommend})",
                f"Создано задач: <b>{len(created)}</b>, уже были: {skipped_existing}",
                "",
                "Топ:",
            ]
            for sku in critical[:8]:
                lines.append(
                    f"• <code>{sku.vendor_code}</code> — "
                    f"~{sku.min_days:.0f} дн., поставить ~{sku.recommend}, "
                    f"заказы {sku.ordered}"
                )
            try:
                await bot.send_message(
                    int(settings.owner_telegram_id),
                    "\n".join(lines),
                    parse_mode="HTML",
                )
            except Exception:  # noqa: BLE001
                logger.exception("stock digest notify failed")

    return {
        "ok": True,
        "target_days": target,
        "critical_total": len(critical),
        "created": created,
        "skipped_existing": skipped_existing,
    }
