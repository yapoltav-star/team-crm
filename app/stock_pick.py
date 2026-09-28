"""Наборы «Наш склад · по артикулам»: свой исполнитель + выбранные vendor_code."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee
from app.watch_assignees import KEY_STOCK_PAUSED, get_setting, is_watch_paused, set_setting

logger = logging.getLogger(__name__)

KEY_STOCK_PICK_ROUTES = "stock_pick_routes"

STOCK_PICK_HOW_IT_WORKS = (
    "Та же проверка остатков на «нашем складе», но только по выбранным артикулам. "
    "Открой карточку — отметь артикулы в таблице и укажи, кому ставить задачи. "
    "Можно сделать несколько наборов: одному человеку — одни артикулы, другому — другие. "
    "Артикулы из активного набора не уходят в общую автозадачу «Наш склад». "
    "Новый набор по умолчанию на паузе — пока не снимешь, по расписанию ничего не создаётся."
)


def _new_route_id() -> str:
    return "sp-" + uuid.uuid4().hex[:10]


def _normalize_codes(codes: list[Any] | None) -> list[str]:
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


def default_stock_pick_route() -> dict[str, Any]:
    return {
        "id": _new_route_id(),
        "label": "Наш склад · по артикулам",
        "paused": True,
        "assignee_id": None,
        "vendor_codes": [],
    }


def _coerce_route(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    rid = str(raw.get("id") or "").strip() or _new_route_id()
    label = str(raw.get("label") or "").strip() or "Наш склад · по артикулам"
    paused = bool(raw.get("paused", True))
    assignee_id = raw.get("assignee_id")
    try:
        assignee_id = int(assignee_id) if assignee_id is not None and str(assignee_id).strip() else None
    except (TypeError, ValueError):
        assignee_id = None
    if assignee_id is not None and assignee_id <= 0:
        assignee_id = None
    codes = _normalize_codes(raw.get("vendor_codes") if isinstance(raw.get("vendor_codes"), list) else [])
    return {
        "id": rid,
        "label": label[:120],
        "paused": paused,
        "assignee_id": assignee_id,
        "vendor_codes": codes,
    }


async def load_stock_pick_routes(session: AsyncSession) -> list[dict[str, Any]]:
    raw = (await get_setting(session, KEY_STOCK_PICK_ROUTES)).strip()
    routes: list[dict[str, Any]] = []
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            for item in data:
                route = _coerce_route(item)
                if route:
                    routes.append(route)
    if not routes:
        routes = [default_stock_pick_route()]
        await save_stock_pick_routes(session, routes)
    return routes


async def save_stock_pick_routes(session: AsyncSession, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for item in routes:
        route = _coerce_route(item)
        if route:
            clean.append(route)
    if not clean:
        clean = [default_stock_pick_route()]
    await set_setting(session, KEY_STOCK_PICK_ROUTES, json.dumps(clean, ensure_ascii=False))
    return clean


async def upsert_stock_pick_route(
    session: AsyncSession,
    *,
    route_id: str | None = None,
    label: str | None = None,
    paused: bool | None = None,
    assignee_id: int | None = None,
    vendor_codes: list[str] | None = None,
    create: bool = False,
) -> dict[str, Any]:
    routes = await load_stock_pick_routes(session)
    target: dict[str, Any] | None = None
    if create or not route_id:
        target = default_stock_pick_route()
        if label is not None and str(label).strip():
            target["label"] = str(label).strip()[:120]
        if paused is not None:
            target["paused"] = bool(paused)
        if assignee_id is not None:
            target["assignee_id"] = int(assignee_id) if int(assignee_id) > 0 else None
        if vendor_codes is not None:
            target["vendor_codes"] = _normalize_codes(vendor_codes)
        routes.append(target)
    else:
        for r in routes:
            if r["id"] == route_id:
                target = r
                break
        if target is None:
            raise KeyError(route_id)
        if label is not None and str(label).strip():
            target["label"] = str(label).strip()[:120]
        if paused is not None:
            target["paused"] = bool(paused)
        if assignee_id is not None:
            target["assignee_id"] = int(assignee_id) if int(assignee_id) > 0 else None
        if vendor_codes is not None:
            target["vendor_codes"] = _normalize_codes(vendor_codes)
    await save_stock_pick_routes(session, routes)
    return target


async def delete_stock_pick_route(session: AsyncSession, route_id: str) -> list[dict[str, Any]]:
    routes = await load_stock_pick_routes(session)
    routes = [r for r in routes if r["id"] != route_id]
    return await save_stock_pick_routes(session, routes)


def route_code_set(route: dict[str, Any]) -> set[str]:
    return {str(c).strip().casefold() for c in (route.get("vendor_codes") or []) if str(c).strip()}


def sku_matches_route(sku_vendor: str, family: list[str] | None, route: dict[str, Any]) -> bool:
    codes = route_code_set(route)
    if not codes:
        return False
    candidates = [sku_vendor, *(family or [])]
    return any(str(c or "").strip().casefold() in codes for c in candidates)


async def resolve_stock_route_assignee(
    session: AsyncSession,
    *,
    sku_vendor: str,
    family: list[str] | None,
    default_assignee: Employee,
    owner: Employee,
    default_paused: bool | None = None,
    ignore_route_pause: bool = False,
) -> tuple[Employee, str]:
    """Кому ставить задачу по SKU.

    Сначала активные наборы по артикулам; иначе общая «Наш склад».
    Возвращает (assignee, source) где source = route_id | 'stock'.
    """
    if default_paused is None:
        default_paused = await is_watch_paused(session, KEY_STOCK_PAUSED)

    routes = await load_stock_pick_routes(session)
    for route in routes:
        if route.get("paused") and not ignore_route_pause:
            continue
        if not route_code_set(route):
            continue
        if not sku_matches_route(sku_vendor, family, route):
            continue
        emp = None
        aid = route.get("assignee_id")
        if aid:
            emp = await session.get(Employee, int(aid))
            if emp and not emp.active:
                emp = None
        if emp is None:
            emp = default_assignee if not default_paused else owner
        return emp, str(route["id"])

    if default_paused:
        raise LookupError("default stock watch paused and no pick route matched")
    return default_assignee, "stock"


async def stock_pick_briefs(
    session: AsyncSession,
    *,
    managers_by_id: dict[int, Employee],
    stock_enabled: bool,
    stock_days: str,
    stock_time: str,
    cooldown_days: int,
) -> list[dict[str, Any]]:
    routes = await load_stock_pick_routes(session)
    out = []
    for r in routes:
        aid = r.get("assignee_id")
        emp = managers_by_id.get(int(aid)) if aid else None
        paused = bool(r.get("paused"))
        codes = list(r.get("vendor_codes") or [])
        out.append(
            {
                "id": r["id"],
                "label": r.get("label") or "Наш склад · по артикулам",
                "kind": "own-stock-pick",
                "enabled": bool(stock_enabled),
                "paused": paused,
                "active": bool(stock_enabled) and not paused and bool(codes) and bool(emp),
                "days": stock_days,
                "time": stock_time,
                "cooldown_days": cooldown_days,
                "how_it_works": STOCK_PICK_HOW_IT_WORKS,
                "assignee_id": emp.id if emp else aid,
                "assignee_name": emp.name if emp else None,
                "vendor_codes": codes,
                "vendor_count": len(codes),
            }
        )
    return out
