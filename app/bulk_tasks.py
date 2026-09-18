"""Разбор одного сообщения с несколькими «Поставь задачу …»."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.audience import (
    _norm,
    find_role_in_text,
    match_person_token,
    resolve_audience,
)
from app.models import Employee

# Одна задача = одна строка «Поставь задачу Кому: текст…»
# (так удобно кидать пачку из транскрипта; между блоками могут быть пояснения)
BULK_TASK_RE = re.compile(
    r"(?im)"
    r"^\s*(?:поставь|назначь|создай)\s+задач[ауею]?\s+"
    r"(?:для\s+|на\s+)?"
    r"(?P<who>"
    r"[«\"„“'\[]\s*[^»\"”'\]]{1,80}?\s*[»\"”'\]]"
    r"|"
    r"[а-яёa-z0-9][а-яёa-z0-9\s\-']{0,60}?"
    r")"
    r"\s*[:\-–—]\s*"
    r"(?P<title>.+?)\s*$"
)

UNRESOLVED_TOKENS = frozenset(
    {
        "ответственный не определен",
        "ответственный не определён",
        "не определен",
        "не определён",
        "неизвестно",
        "без ответственного",
        "кто-то",
        "кто нибудь",
        "кто-нибудь",
    }
)

TEAM_TOKENS = frozenset(
    {
        "команда",
        "команде",
        "всем",
        "всех",
        "все",
        "всей команде",
        "группа",
        "группе",
    }
)


@dataclass
class BulkTaskItem:
    assignee_raw: str
    title: str


def _strip_quotes(value: str) -> str:
    s = (value or "").strip()
    if len(s) >= 2 and s[0] in "«\"„“'[" and s[-1] in "»\"”']":
        return s[1:-1].strip()
    return s.strip(" «»\"'„“”[]")


def parse_bulk_task_items(text: str) -> list[BulkTaskItem]:
    """Вытащить все блоки «поставь задачу Кому: текст» из сообщения."""
    raw = (text or "").strip()
    if not raw:
        return []
    items: list[BulkTaskItem] = []
    for m in BULK_TASK_RE.finditer(raw):
        who = _strip_quotes(m.group("who") or "")
        title = re.sub(r"\s+", " ", (m.group("title") or "").strip())
        title = title.strip(" .,;—-\n\t")
        if not who or not title:
            continue
        # отсечь вводные вроде «Есть ещё несколько поручений…»
        if len(title) < 3:
            continue
        items.append(BulkTaskItem(assignee_raw=who, title=title))
    return items


def count_task_verbs(text: str) -> int:
    return len(
        re.findall(
            r"(?i)(?:^|\n)\s*(?:поставь|назначь|создай)\s+задач",
            text or "",
        )
    )


def resolve_bulk_assignees(
    people: list[Employee],
    assignee_raw: str,
    *,
    author: Employee,
) -> tuple[list[Employee], str | None]:
    """
    Вернуть (исполнители, предупреждение).

    warning — если повесили на автора из‑за «не определён» / не нашли имя.
    """
    raw = _strip_quotes(assignee_raw)
    token = _norm(raw)
    if not token:
        return [author], "адресат пуст — поставил(а) тебе"

    if token in UNRESOLVED_TOKENS or token.startswith("ответственный не"):
        return [author], f"«{raw}» — повесил(а) на тебя, перекинь кому нужно"

    if token in TEAM_TOKENS:
        team = [p for p in people if p.active and p.role != "owner" and p.id != author.id]
        if not team:
            team = [p for p in people if p.active and p.id != author.id]
        if team:
            return team, None
        return [author], "команду не нашёл — поставил(а) тебе"

    emp = match_person_token(people, raw)
    if emp:
        return [emp], None

    # роль: «складу», «поддержке», «рук»
    role = find_role_in_text(raw) or find_role_in_text(f"задача {raw}")
    if role:
        audience = resolve_audience(people, token=f"role:{role}", raw_text=raw)
        if audience:
            return audience, None

    return [author], f"не нашёл «{raw}» — поставил(а) тебе, перекинь"
