"""Должности менеджеров (не путать с role=owner|manager для доступа)."""

from __future__ import annotations

JOB_TITLES: tuple[str, ...] = (
    "поддержка",
    "менеджер",
    "склад",
    "партнер",
    "рук",
    "менеджер по китаю",
)

JOB_TITLE_SET = frozenset(JOB_TITLES)
