"""Автозадачи по слабым полкам своих карточек (WB Dashboard → Полки у моих).

Правило: в топ-15 «Смотрите также» доля своих (PVS / свои nm) < порога → задача.
"""

from __future__ import annotations

import asyncio
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

logger = logging.getLogger("shelf-watch")

MARKER_PREFIX = "[auto:my-shelf:"


@dataclass
class WeakShelf:
    nm_id: int
    vendor_code: str
    mine_pct: float
    mine_count: int
    total: int
    ordered_qty: int
    city: str
    name: str


def _marker(nm_id: int) -> str:
    return f"{MARKER_PREFIX}{int(nm_id)}]"


def is_shelf_mine(item: dict[str, Any], own_nms: set[int]) -> bool:
    try:
        nm = int(item.get("nm_id"))
    except (TypeError, ValueError):
        nm = None
    if nm is not None and nm in own_nms:
        return True
    return str(item.get("brand") or "").strip().upper() == "PVS"


def shelf_mine_share(items: list[dict[str, Any]], own_nms: set[int]) -> tuple[float, int, int]:
    total = len(items)
    if total <= 0:
        return 0.0, 0, 0
    mine = sum(1 for it in items if is_shelf_mine(it, own_nms))
    pct = round((mine / total) * 1000) / 10
    return pct, mine, total


async def fetch_json(url: str) -> Any:
    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _blocked_markers(session: AsyncSession, *, cooldown_days: int) -> set[str]:
    cutoff = datetime.utcnow() - timedelta(days=max(1, cooldown_days))
    tasks = (await session.scalars(select(Task).where(Task.active.is_(True)))).all()
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


async def scan_weak_shelves(
    *,
    base_url: str,
    min_mine_pct: float,
    dest: int,
    delay_sec: float,
    min_orders: int,
) -> tuple[list[WeakShelf], dict[str, Any]]:
    """Тянет карточки с продажами и их полки; возвращает слабые + meta."""
    base = base_url.rstrip("/")
    own_payload = await fetch_json(f"{base}/api/own-articles-all")
    if not isinstance(own_payload, dict):
        raise ValueError("own-articles-all: ожидался объект")
    if own_payload.get("error") and not (own_payload.get("articles") or []):
        raise ValueError(str(own_payload.get("error")))

    articles = own_payload.get("articles") or []
    own_nms = set()
    for a in articles:
        try:
            own_nms.add(int(a.get("nm_id")))
        except (TypeError, ValueError):
            continue

    weak: list[WeakShelf] = []
    errors = 0
    checked = 0
    for a in articles:
        try:
            nm = int(a.get("nm_id"))
        except (TypeError, ValueError):
            continue
        ordered = int(a.get("ordered_qty") or 0)
        if ordered < max(0, min_orders):
            continue
        vc = str(a.get("vendor_code") or nm).strip()
        try:
            data = await fetch_json(
                f"{base}/api/competitor-shelf?nm_id={nm}&dest={dest}&limit=15"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("shelf fetch %s failed: %s", nm, exc)
            errors += 1
            await asyncio.sleep(max(0.1, delay_sec))
            continue
        if not isinstance(data, dict):
            errors += 1
            await asyncio.sleep(max(0.1, delay_sec))
            continue
        items = data.get("items") or []
        if not items:
            await asyncio.sleep(max(0.1, delay_sec))
            continue
        checked += 1
        pct, mine_count, total = shelf_mine_share(items, own_nms)
        if pct < float(min_mine_pct):
            comp = data.get("competitor") or {}
            weak.append(
                WeakShelf(
                    nm_id=nm,
                    vendor_code=vc,
                    mine_pct=pct,
                    mine_count=mine_count,
                    total=total,
                    ordered_qty=ordered,
                    city=str(data.get("city") or ""),
                    name=str(comp.get("name") or ""),
                )
            )
        await asyncio.sleep(max(0.1, delay_sec))

    weak.sort(key=lambda x: (x.mine_pct, -x.ordered_qty, x.vendor_code))
    meta = {
        "articles_total": len(articles),
        "checked": checked,
        "errors": errors,
        "days": own_payload.get("days"),
        "threshold": min_mine_pct,
    }
    return weak, meta


async def run_shelf_watch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    bot=None,
) -> dict[str, Any]:
    if not settings.shelf_watch_enabled:
        return {"ok": False, "skipped": "disabled"}
    if not settings.wb_dashboard_url:
        return {"ok": False, "error": "WB_DASHBOARD_URL пуст"}

    try:
        weak, meta = await scan_weak_shelves(
            base_url=settings.wb_dashboard_url,
            min_mine_pct=settings.shelf_min_mine_pct,
            dest=settings.shelf_dest,
            delay_sec=settings.shelf_request_delay_sec,
            min_orders=settings.shelf_min_orders,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("shelf scan failed")
        return {"ok": False, "error": f"scan: {exc}"}

    top = weak[: max(1, settings.shelf_max_tasks)]
    created: list[dict[str, Any]] = []
    skipped_cooldown = 0

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
            return {"ok": False, "error": "владелец не найден в CRM", **meta}

        assignee = owner
        assignee_tg = settings.shelf_assignee_telegram_id or settings.stock_assignee_telegram_id
        if assignee_tg:
            emp = await session.scalar(
                select(Employee).where(
                    Employee.telegram_id == int(assignee_tg),
                    Employee.active.is_(True),
                )
            )
            if emp:
                assignee = emp

        existing = await _blocked_markers(
            session, cooldown_days=settings.shelf_cooldown_days
        )
        today = datetime.now(settings.tz).date()

        for row in top:
            marker = _marker(row.nm_id)
            if marker in existing:
                skipped_cooldown += 1
                continue

            title = (
                f"Полка слабая: {row.vendor_code} — моя доля {row.mine_pct}% "
                f"(<{settings.shelf_min_mine_pct:g}%)"
            )
            desc = marker
            task = Task(
                title=title[:500],
                description=desc,
                articles=(row.vendor_code[:500]),
                assignee_id=assignee.id,
                created_by_id=owner.id,
                status="todo",
                kind="once",
                notify_time=datetime.now(settings.tz).strftime("%H:%M"),
                due_date=today + timedelta(days=2),
                priority="high" if row.mine_pct < 40 else "normal",
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
                f"Авто: полка {row.vendor_code} — {row.mine_pct}% "
                f"({row.mine_count}/{row.total})",
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
                    "vendor_code": row.vendor_code,
                    "nm_id": row.nm_id,
                    "mine_pct": row.mine_pct,
                    "mine_count": row.mine_count,
                    "total": row.total,
                    "ordered_qty": row.ordered_qty,
                    "notified": notified,
                    "notify_error": nerr,
                }
            )
            existing.add(marker)

        if created and bot:
            lines = [
                f"📦 <b>Полки своих</b>: новые задачи <b>{len(created)}</b> "
                f"(слабых {len(weak)}, кулдаун {skipped_cooldown})",
                f"Порог: моя доля &lt; {settings.shelf_min_mine_pct:g}% в топ-15",
                "",
                "Создано:",
            ]
            for row in created[:12]:
                lines.append(
                    f"• <code>{row['vendor_code']}</code> — "
                    f"{row['mine_pct']}% ({row['mine_count']}/{row['total']})"
                )
            try:
                await bot.send_message(
                    int(settings.owner_telegram_id),
                    "\n".join(lines),
                    parse_mode="HTML",
                )
            except Exception:  # noqa: BLE001
                logger.exception("shelf digest notify failed")

    return {
        "ok": True,
        "mode": "my_shelves",
        "weak_total": len(weak),
        "created": created,
        "skipped_cooldown": skipped_cooldown,
        "weak_preview": [
            {
                "vendor_code": w.vendor_code,
                "nm_id": w.nm_id,
                "mine_pct": w.mine_pct,
                "mine_count": w.mine_count,
                "total": w.total,
                "ordered_qty": w.ordered_qty,
            }
            for w in weak[:20]
        ],
        **meta,
    }
