"""Проверка пароля сайта CRM."""

from __future__ import annotations

import hmac
import secrets
from base64 import b64decode

from fastapi import Request

from app.config import Settings


def _extract_basic(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("basic "):
        return None
    try:
        raw = b64decode(auth.split(" ", 1)[1]).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    if ":" not in raw:
        return None
    # user:password — user игнорируем
    return raw.split(":", 1)[1]


def request_password(request: Request) -> str | None:
    header = request.headers.get("x-crm-password")
    if header:
        return header
    cookie = request.cookies.get("crm_password")
    if cookie:
        return cookie
    # только для ручных curl, не для HTML
    q = request.query_params.get("password")
    if q:
        return q
    return _extract_basic(request)


def password_ok(settings: Settings, candidate: str | None) -> bool:
    expected = (settings.web_password or "").strip()
    if not expected:
        return False
    if candidate is None:
        return False
    return hmac.compare_digest(candidate.strip(), expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(24)
