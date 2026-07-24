"""Разбор «кому задача»: проект (ПВС) + роль (менеджер), а не «всем подряд»."""

from __future__ import annotations

import re

from app.job_titles import JOB_TITLES
from app.models import Employee

# словоформы ролей → канонический job_title
ROLE_FORMS: dict[str, str] = {}
for _title in JOB_TITLES:
    ROLE_FORMS[_title] = _title

ROLE_FORMS.update(
    {
        "менеджера": "менеджер",
        "менеджеру": "менеджер",
        "менеджером": "менеджер",
        "менеджеры": "менеджер",
        "менеджерам": "менеджер",
        "менеджеров": "менеджер",
        "менеджерами": "менеджер",
        "поддержки": "поддержка",
        "поддержке": "поддержка",
        "поддержкой": "поддержка",
        "саппорт": "поддержка",
        "саппорта": "поддержка",
        "support": "поддержка",
        "склада": "склад",
        "складу": "склад",
        "складом": "склад",
        "складские": "склад",
        "складским": "склад",
        "партнёра": "партнер",
        "партнера": "партнер",
        "партнёру": "партнер",
        "партнеру": "партнер",
        "партнёры": "партнер",
        "партнеры": "партнер",
        "партнёрам": "партнер",
        "партнерам": "партнер",
        "партнер": "партнер",
        "партнёр": "партнер",
        "рука": "рук",
        "руку": "рук",
        "руководителю": "рук",
        "руководитель": "рук",
        "руководителям": "рук",
        "китаю": "менеджер по китаю",
        "китая": "менеджер по китаю",
        "китай": "менеджер по китаю",
    }
)

# «менеджер по китаю» целиком
ROLE_PHRASES: list[tuple[str, str]] = [
    (r"менеджер\w*\s+по\s+китаю", "менеджер по китаю"),
]

ALL_ONLY_RE = re.compile(
    r"(?i)(?<![а-яa-z0-9])"
    r"(?:всем|всех|на\s+всех|для\s+всех|всей\s+команде|всей\s+группе)"
    r"(?![а-яa-z0-9])"
)

AUDIENCE_STRIP_RE = re.compile(
    r"(?i)\s*(?:поставь|назначь|создай)?\s*"
    r"(?:задач[ауе]?\s+)?"
    r"(?:для\s+|на\s+)?"
    r"(?:всем\s+)?"
    r"(?:"
    r"менеджер\w*(?:\s+по\s+китаю)?|"
    r"поддержк\w*|склад\w*|партн[её]р\w*|рук\w*|"
    r"саппорт\w*|support"
    r")\s*"
    r"(?:на\s+|в\s+|проекта?\s+|группы?\s+)?"
    r"[«\"]?([a-zа-яё0-9][\w\-а-яё]*)[»\"]?\s*"
    r"(?:на\s+проекте|проекта)?\s*[:\-]?\s*",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower().replace("ё", "е"))


def project_names(people: list[Employee]) -> list[str]:
    names = {(e.team_group or "").strip() for e in people if (e.team_group or "").strip()}
    return sorted(names, key=len, reverse=True)


def find_project_in_text(text: str, people: list[Employee]) -> str | None:
    blob = _norm(text)
    for name in project_names(people):
        n = _norm(name)
        if not n:
            continue
        if re.search(rf"(?<![а-яa-z0-9]){re.escape(n)}(?![а-яa-z0-9])", blob):
            return name
    return None


def find_role_in_text(text: str) -> str | None:
    blob = _norm(text)
    for pat, title in ROLE_PHRASES:
        if re.search(pat, blob, flags=re.IGNORECASE):
            return title
    # длинные формы сначала
    for form in sorted(ROLE_FORMS.keys(), key=len, reverse=True):
        if re.search(rf"(?<![а-яa-z0-9]){re.escape(_norm(form))}(?![а-яa-z0-9])", blob):
            return ROLE_FORMS[form]
    return None


def filter_by_audience(
    people: list[Employee],
    *,
    project: str | None = None,
    job_title: str | None = None,
    include_owner: bool = False,
) -> list[Employee]:
    out: list[Employee] = []
    proj = _norm(project or "")
    role = _norm(job_title or "")
    for e in people:
        if not include_owner and e.role == "owner":
            continue
        if proj and _norm(e.team_group or "") != proj:
            continue
        if role and _norm(e.job_title or "") != role:
            continue
        out.append(e)
    return out


def resolve_audience(
    people: list[Employee],
    *,
    token: str = "",
    raw_text: str = "",
) -> list[Employee] | None:
    """
    Вернуть список исполнителей или None, если аудиторию не распознали
    (тогда вызывающий код ищет по имени / all).
    """
    blob = f"{token} {raw_text}".strip()
    if not blob:
        return None

    project = find_project_in_text(blob, people)
    role = find_role_in_text(blob)

    # явный формат из NLP: project:ПВС | role:менеджер | ПВС/менеджер
    t = (token or "").strip()
    if t.lower().startswith("project:"):
        project = project or t.split(":", 1)[1].strip()
    if t.lower().startswith("role:"):
        role = role or ROLE_FORMS.get(_norm(t.split(":", 1)[1]), _norm(t.split(":", 1)[1]))
    if "/" in t and not t.lower().startswith("http"):
        left, right = [x.strip() for x in t.split("/", 1)]
        if left and right:
            # ПВС/менеджер или менеджер/ПВС
            if _norm(left) in {_norm(p) for p in project_names(people)} or find_project_in_text(
                left, people
            ):
                project = project or find_project_in_text(left, people) or left
                role = role or find_role_in_text(right) or ROLE_FORMS.get(_norm(right), _norm(right))
            else:
                role = role or find_role_in_text(left) or ROLE_FORMS.get(_norm(left), _norm(left))
                project = project or find_project_in_text(right, people) or right

    if not project and not role:
        return None

    targets = filter_by_audience(people, project=project, job_title=role)
    return targets  # может быть пустым — это «поняли аудиторию, но никого нет»


def is_literal_all(token: str, raw_text: str, people: list[Employee]) -> bool:
    """Только явное «всем», и только если нет проекта/роли в фразе."""
    if resolve_audience(people, token=token, raw_text=raw_text) is not None:
        return False
    t = _norm(token)
    if t in {
        "all",
        "team",
        "всем",
        "всех",
        "все",
        "everyone",
        "на всех",
        "для всех",
        "команда",
        "команде",
    }:
        return True
    return bool(ALL_ONLY_RE.search(raw_text or ""))


def strip_audience_from_title(title: str, people: list[Employee]) -> str:
    """Убрать из текста задачи «менеджерам ПВС» и т.п."""
    raw = (title or "").strip()
    if not raw:
        return raw
    # вырезать известные проекты и роли в начале / после «задачу»
    out = raw
    proj = find_project_in_text(out, people)
    role = find_role_in_text(out)
    if role:
        for form, canon in ROLE_FORMS.items():
            if canon != role:
                continue
            out = re.sub(
                rf"(?i)(?<![а-яa-z0-9]){re.escape(form)}(?![а-яa-z0-9])",
                " ",
                out,
            )
        if role == "менеджер по китаю":
            out = re.sub(r"(?i)менеджер\w*\s+по\s+китаю", " ", out)
    if proj:
        out = re.sub(
            rf"(?i)(?<![а-яa-z0-9]){re.escape(proj)}(?![а-яa-z0-9])",
            " ",
            out,
        )
    out = re.sub(
        r"(?i)\b(?:поставь|назначь|создай)\s+(?:задач[ауе]?\s+)?",
        " ",
        out,
    )
    out = re.sub(r"(?i)\b(?:задач[ауе]|для|на|проекта?|группы?)\b", " ", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" .,!—-:\n\t")
    return out or raw
