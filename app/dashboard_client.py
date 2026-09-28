"""Клиент WB Dashboard: логин (SITE_PASSWORD) + JSON API."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import aiohttp

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

WB_RF_RE = re.compile(r"(?:склад\s+)?(?:wb|вб)[\s\-]*рф", re.I)

_COOKIE_JAR: aiohttp.CookieJar | None = None
_COOKIE_OK_UNTIL = 0.0
_WB_RF_CACHE: dict[str, int] = {}
_WB_RF_CACHE_UNTIL = 0.0
_WB_RF_TTL_SEC = 120.0
_OWN_WH_CACHE: dict[str, int] = {}
_OWN_WH_CACHE_UNTIL = 0.0
_OWN_WH_TTL_SEC = 120.0


def _base_url(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return (s.wb_dashboard_url or "").rstrip("/")


def _password(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return (getattr(s, "wb_dashboard_password", None) or "").strip()


async def _ensure_login(session: aiohttp.ClientSession, settings: Settings) -> None:
    """Если у дашборда включён SITE_PASSWORD — логинимся и кладём cookie."""
    global _COOKIE_OK_UNTIL
    pwd = _password(settings)
    if not pwd:
        return
    now = time.time()
    if now < _COOKIE_OK_UNTIL:
        return
    base = _base_url(settings)
    async with session.post(
        f"{base}/api/login",
        json={"password": pwd},
        headers={"Content-Type": "application/json"},
    ) as resp:
        if resp.status >= 400:
            text = (await resp.text())[:200]
            raise RuntimeError(f"dashboard login {resp.status}: {text}")
        data = await resp.json(content_type=None)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"dashboard login: {data.get('error')}")
    # cookie живёт долго на дашборде; обновляем запас раз в сутки
    _COOKIE_OK_UNTIL = now + 20 * 3600


async def fetch_dashboard_json(
    path: str,
    *,
    settings: Settings | None = None,
    timeout_sec: float = 60,
) -> Any:
    """GET JSON с дашборда (с логином при необходимости). path: '/api/...'."""
    global _COOKIE_JAR
    s = settings or get_settings()
    base = _base_url(s)
    if not base:
        raise RuntimeError("WB_DASHBOARD_URL пуст")
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    if _COOKIE_JAR is None:
        _COOKIE_JAR = aiohttp.CookieJar(unsafe=True)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout, cookie_jar=_COOKIE_JAR) as session:
        await _ensure_login(session, s)
        async with session.get(url) as resp:
            if resp.status == 401 and _password(s):
                # cookie протухла — ещё раз
                global _COOKIE_OK_UNTIL
                _COOKIE_OK_UNTIL = 0.0
                await _ensure_login(session, s)
                async with session.get(url) as resp2:
                    resp2.raise_for_status()
                    return await resp2.json(content_type=None)
            resp.raise_for_status()
            return await resp.json(content_type=None)


def _wb_rf_qty_from_product(product: dict[str, Any]) -> int:
    total = 0
    for w in product.get("warehouses") or []:
        if not isinstance(w, dict):
            continue
        name = str(w.get("name") or "")
        if not WB_RF_RE.search(name):
            continue
        try:
            total += int(w.get("qty") or 0)
        except (TypeError, ValueError):
            pass
    return max(0, total)


async def fetch_wb_rf_stock_by_vendor(
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, int]:
    """vendor_code (casefold) → штуки на «Склад WB РФ» из /api/wb-products."""
    global _WB_RF_CACHE, _WB_RF_CACHE_UNTIL
    now = time.time()
    if not force and _WB_RF_CACHE and now < _WB_RF_CACHE_UNTIL:
        return dict(_WB_RF_CACHE)
    raw = await fetch_dashboard_json("/api/wb-products", settings=settings, timeout_sec=90)
    if not isinstance(raw, dict):
        raise ValueError("wb-products: ожидался объект")
    if raw.get("error") and not (raw.get("products") or []):
        raise RuntimeError(f"wb-products: {raw.get('error')}")
    out: dict[str, int] = {}
    for p in raw.get("products") or []:
        if not isinstance(p, dict):
            continue
        vc = str(p.get("vendor_code") or "").strip()
        if not vc:
            continue
        qty = _wb_rf_qty_from_product(p)
        key = vc.casefold()
        # если несколько nm на один vendor — суммируем
        out[key] = int(out.get(key) or 0) + qty
    _WB_RF_CACHE = out
    _WB_RF_CACHE_UNTIL = now + _WB_RF_TTL_SEC
    logger.info("wb-rf stock map: %s vendor codes", len(out))
    return dict(out)


async def fetch_own_warehouse_stock_by_vendor(
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, int]:
    """vendor_code (casefold) → остаток семьи на «нашем складе» (family_stock)."""
    global _OWN_WH_CACHE, _OWN_WH_CACHE_UNTIL
    now = time.time()
    if not force and _OWN_WH_CACHE and now < _OWN_WH_CACHE_UNTIL:
        return dict(_OWN_WH_CACHE)
    raw = await fetch_dashboard_json(
        "/api/own-warehouse-stock", settings=settings, timeout_sec=90
    )
    if not isinstance(raw, dict):
        raise ValueError("own-warehouse-stock: ожидался объект")
    if raw.get("error") and not (raw.get("by_vendor") or {}):
        raise RuntimeError(f"own-warehouse: {raw.get('error')}")
    out: dict[str, int] = {}
    by_vendor = raw.get("by_vendor") or {}
    if not isinstance(by_vendor, dict):
        by_vendor = {}
    for vc, meta in by_vendor.items():
        key = str(vc or "").strip().casefold()
        if not key or not isinstance(meta, dict):
            continue
        try:
            personal = int(meta.get("stock") or 0)
        except (TypeError, ValueError):
            personal = 0
        fam = meta.get("family_stock")
        try:
            family_stock = int(fam) if fam is not None else personal
        except (TypeError, ValueError):
            family_stock = personal
        family_stock = max(0, family_stock)
        out[key] = family_stock
        for member in meta.get("family") or []:
            mk = str(member or "").strip().casefold()
            if mk:
                # один остаток семьи на всех членов
                out[mk] = family_stock
    _OWN_WH_CACHE = out
    _OWN_WH_CACHE_UNTIL = now + _OWN_WH_TTL_SEC
    logger.info("own-wh stock map: %s vendor codes", len(out))
    return dict(out)
