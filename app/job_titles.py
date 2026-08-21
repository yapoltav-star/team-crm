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

# партнёр видит всех сотрудников своего проекта (team_group)
PROJECT_WIDE_TITLES = frozenset({"партнер"})


def norm_job_title(value: str | None) -> str:
    return (value or "").strip().lower().replace("ё", "е")


def is_partner_title(job_title: str | None) -> bool:
    return norm_job_title(job_title) == "партнер"


def is_ruk_title(job_title: str | None) -> bool:
    return norm_job_title(job_title) == "рук"


def sees_project_team(job_title: str | None) -> bool:
    """Партнёр видит команду своего проекта."""
    return norm_job_title(job_title) in PROJECT_WIDE_TITLES


def can_view_all_employees(
    *, role: str | None = None, job_title: str | None = None
) -> bool:
    """Владелец или рук — видят всех сотрудников компании."""
    if (role or "") == "owner":
        return True
    return is_ruk_title(job_title)


def can_reassign_tasks(*, role: str | None = None, job_title: str | None = None) -> bool:
    """Владелец или рук — могут перекидывать задачи."""
    if (role or "") == "owner":
        return True
    return is_ruk_title(job_title)


def can_nudge_tasks(*, role: str | None = None, job_title: str | None = None) -> bool:
    """Можно напоминать по чужим задачам: владелец, рук, партнёр."""
    return can_view_all_employees(role=role, job_title=job_title) or is_partner_title(
        job_title
    )
