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

# видят всех сотрудников своего проекта (team_group) и могут перекидывать задачи
PROJECT_WIDE_TITLES = frozenset({"партнер", "рук"})


def norm_job_title(value: str | None) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def sees_project_team(job_title: str | None) -> bool:
    return norm_job_title(job_title) in PROJECT_WIDE_TITLES


def can_reassign_tasks(*, role: str | None = None, job_title: str | None = None) -> bool:
    """Владелец или рук — могут перекидывать задачи."""
    if (role or "") == "owner":
        return True
    return norm_job_title(job_title) == "рук"
