"""Разбор «кому задача»: имя человека важнее случайного «ПВС» в тексте бренда."""

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

ROLE_PHRASES: list[tuple[str, str]] = [
    (r"менеджер\w*\s+по\s+китаю", "менеджер по китаю"),
]

ALL_ONLY_RE = re.compile(
    r"(?i)(?<![а-яa-z0-9])"
    r"(?:всем|всех|на\s+всех|для\s+всех|всей\s+команде|всей\s+группе)"
    r"(?![а-яa-z0-9])"
)

# явные обращения «поставь задачу Софии / для Вани / Соне: …»
NAME_ASSIGN_RE = re.compile(
    r"(?i)(?:^|[.!?]\s*)"
    r"(?:поставь|назначь|создай|сделай)?\s*"
    r"(?:пожалуйста\s+)?"
    r"(?:задач[ауею]\s+)?"
    r"(?:для\s+|на\s+)?"
    r"([а-яёa-z][а-яёa-z\-']{1,30})"
    r"(?:\s*[,:]|\s+(?:чтобы|разобрать|сделать|проверить|загрузить|написать|ответить|"
    r"связаться|посмотреть|подготовить|согласовать|отправить|взять|закрыть)\b)",
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
    for form in sorted(ROLE_FORMS.keys(), key=len, reverse=True):
        if re.search(rf"(?<![а-яa-z0-9]){re.escape(_norm(form))}(?![а-яa-z0-9])", blob):
            return ROLE_FORMS[form]
    return None


def _name_stem(name: str) -> str:
    """Упрощённая основа русского имени: София → софи, Иван → иван."""
    first = _norm(name).split()[0] if name else ""
    if len(first) < 3:
        return first
    endings = (
        "ией",
        "иею",
        "ьею",
        "ьей",
        "ию",
        "ии",
        "ье",
        "ья",
        "ью",
        "ей",
        "ой",
        "ом",
        "ем",
        "у",
        "ю",
        "а",
        "я",
        "е",
        "и",
        "ы",
        "о",
    )
    for end in endings:
        if first.endswith(end) and len(first) - len(end) >= 3:
            return first[: -len(end)]
    return first


def match_person_token(people: list[Employee], token: str) -> Employee | None:
    """Сопоставить токен имени (в т.ч. падеж/уменьшительное) с сотрудником."""
    t = _norm(token)
    if not t or len(t) < 2:
        return None
    # точные / подстрочные совпадения по полному имени
    for p in people:
        full = _norm(p.name)
        if t == full or t in full.split() or full in t:
            return p
    stem = _name_stem(t) if len(t) >= 3 else t
    if len(stem) < 3:
        stem = t
    best: Employee | None = None
    best_score = 0
    for p in people:
        parts = _norm(p.name).split()
        for part in parts:
            pstem = _name_stem(part)
            if stem == pstem or part.startswith(stem) or stem.startswith(pstem[: max(3, len(pstem) - 1)]):
                score = len(stem)
                # «соне» ↔ «софия»: общая основа «со»
                if stem[:3] == pstem[:3] and len(stem) >= 3:
                    score = max(score, 3)
                if score > best_score:
                    best = p
                    best_score = score
            # уменьшительные: соня/соне ↔ софия
            if part.startswith("софи") and t.startswith("сон"):
                return p
            if pstem.startswith("сон") and t.startswith("софи"):
                return p
    return best if best_score >= 3 else None


def find_named_assignees(text: str, people: list[Employee]) -> list[Employee]:
    """
    Кому именно поставили задачу по имени.
    «Поставь задачу Софии разобраться с брендом ПВС» → [София],
    а не вся группа ПВС.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    found: list[Employee] = []
    seen: set[int] = set()

    def add(emp: Employee | None) -> None:
        if emp and emp.id not in seen:
            seen.add(emp.id)
            found.append(emp)

    for m in NAME_ASSIGN_RE.finditer(raw):
        token = next((g for g in m.groups() if g), "")
        if not token:
            continue
        # служебные слова — не имена
        if _norm(token) in {
            "задачу",
            "задача",
            "всем",
            "всех",
            "себе",
            "мне",
            "боссу",
            "мне",
            "пожалуйста",
            "сегодня",
            "завтра",
            "сроком",
        }:
            continue
        # не путать проект с именем
        if find_project_in_text(token, people):
            continue
        if find_role_in_text(token):
            continue
        add(match_person_token(people, token))

    # запасной путь: «… Софии …» / «Соне» рядом с «задач»
    if not found and re.search(r"(?i)задач", raw):
        for p in people:
            first = _norm(p.name).split()[0]
            stem = _name_stem(first)
            if len(stem) < 3:
                continue
            if re.search(
                rf"(?i)(?<![а-яa-z0-9]){re.escape(stem)}[а-яёa-z]*",
                raw,
            ):
                # имя должно быть до описания работы / рядом с «задач»
                add(p)

    # «Соне» ↔ София вручную, если в тексте есть сон*
    if not found:
        if re.search(r"(?i)(?<![а-яa-z0-9])сон[еяиью]?(?![а-яa-z0-9])", raw):
            for p in people:
                if _norm(p.name).split()[0].startswith("софи"):
                    add(p)
                    break

    return found


def project_audience_intent(text: str, people: list[Employee]) -> str | None:
    """
    Проект как адресат только при явном намерении:
    «всем на ПВС», «команде ПВС», «задачу на ПВС», «ПВС: …».
    Упоминание «бренд ПВС» сюда не попадает.
    """
    blob = _norm(text)
    for name in project_names(people):
        n = _norm(name)
        if not n:
            continue
        patterns = [
            rf"(?:всем|всех|команде|группе|проекту)\s+(?:на\s+|в\s+|из\s+)?{re.escape(n)}",
            rf"(?:на|для)\s+(?:проекте?\s+|группе?\s+|команде?\s+)?{re.escape(n)}"
            rf"(?![а-яa-z0-9])",
            rf"задач[ауею]?\s+(?:на\s+|для\s+|в\s+)?{re.escape(n)}(?![а-яa-z0-9])",
            rf"(?<![а-яa-z0-9]){re.escape(n)}\s*[:\-]",
        ]
        for pat in patterns:
            if re.search(pat, blob):
                return name
    return None


def project_bound_to_role(text: str, people: list[Employee]) -> str | None:
    """«менеджерам ПВС» / «складу на ПВС» — проект сразу после роли, не «бренд ПВС» в конце."""
    blob = _norm(text)
    if not blob:
        return None
    for name in project_names(people):
        n = _norm(name)
        if not n:
            continue
        for form in sorted(ROLE_FORMS.keys(), key=len, reverse=True):
            f = _norm(form)
            if re.search(
                rf"(?<![а-яa-z0-9]){re.escape(f)}\s+"
                rf"(?:на\s+|в\s+|из\s+|проекта?\s+|группы?\s+)?"
                rf"{re.escape(n)}(?![а-яa-z0-9])",
                blob,
            ):
                return name
        for pat, _title in ROLE_PHRASES:
            if re.search(
                rf"(?:{pat})\s+(?:на\s+|в\s+|из\s+|проекта?\s+|группы?\s+)?"
                rf"{re.escape(n)}(?![а-яa-z0-9])",
                blob,
                flags=re.IGNORECASE,
            ):
                return name
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
    Вернуть список исполнителей или None, если аудиторию не распознали.

    Важно: голое слово проекта в тексте задачи («бренд ПВС») — это НЕ
    назначение всей группе. Нужна роль и/или явный адресат-проект.
    """
    blob = f"{token} {raw_text}".strip()
    if not blob:
        return None

    # имя человека важнее группы — но resolve_audience про аудиторию;
    # имена обрабатывает вызывающий код (bot) через find_named_assignees.

    project: str | None = None
    role = find_role_in_text(blob)

    t = (token or "").strip()
    if t.lower().startswith("project:"):
        project = t.split(":", 1)[1].strip() or None
    if t.lower().startswith("role:"):
        role = role or ROLE_FORMS.get(_norm(t.split(":", 1)[1]), _norm(t.split(":", 1)[1]))
    if "/" in t and not t.lower().startswith("http"):
        left, right = [x.strip() for x in t.split("/", 1)]
        if left and right:
            if _norm(left) in {_norm(p) for p in project_names(people)} or find_project_in_text(
                left, people
            ):
                project = project or find_project_in_text(left, people) or left
                role = role or find_role_in_text(right) or ROLE_FORMS.get(_norm(right), _norm(right))
            else:
                role = role or find_role_in_text(left) or ROLE_FORMS.get(_norm(left), _norm(left))
                project = project or find_project_in_text(right, people) or right

    # проект: явный адресат ИЛИ рядом с ролью («менеджерам ПВС»)
    if not project:
        project = project_audience_intent(raw_text or blob, people) or project_bound_to_role(
            raw_text or blob, people
        )

    # роль без проекта — ок («менеджерам …»)
    if not project and not role:
        return None

    # голый project: из token — ок; голое слово проекта в тексте — нет
    if project and not role and not project_audience_intent(raw_text or blob, people):
        if not (t.lower().startswith("project:") or ("/" in t)):
            return None

    targets = filter_by_audience(people, project=project, job_title=role)
    return targets


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
    """Убрать из текста задачи адресата («менеджерам ПВС», «Софии»), не трогая смысл."""
    raw = (title or "").strip()
    if not raw:
        return raw
    out = raw

    # снять «поставь задачу Софии» — только если это имя, не роль/проект
    m_name = re.match(
        r"(?i)^\s*(?:поставь|назначь|создай|сделай)?\s*"
        r"(?:пожалуйста\s+)?"
        r"(?:задач[ауею]\s+)?"
        r"(?:для\s+|на\s+)?"
        r"([а-яёa-z][а-яёa-z\-']{1,30})\s*[,:]?\s*",
        out,
    )
    if m_name:
        token = m_name.group(1)
        is_role = bool(find_role_in_text(token)) or _norm(token) in ROLE_FORMS
        is_proj = bool(find_project_in_text(token, people))
        if not is_role and not is_proj and match_person_token(people, token):
            out = out[m_name.end() :]

    role = find_role_in_text(raw)
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

    # проект вырезаем только если это был адресат, не часть бренда
    proj = project_audience_intent(raw, people) or (
        project_bound_to_role(raw, people) if role else None
    )
    if proj:
        out = re.sub(
            rf"(?i)(?:\b(?:на|в|для|из)\s+)?(?<![а-яa-z0-9]){re.escape(proj)}(?![а-яa-z0-9])",
            " ",
            out,
        )

    out = re.sub(
        r"(?i)\b(?:поставь|назначь|создай|сделай)\s+(?:задач[ауею]?\s+)?",
        " ",
        out,
    )
    out = re.sub(r"(?i)\b(?:задач[ауею])\b", " ", out)
    out = ALL_ONLY_RE.sub(" ", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" .,!—-:\n\t")
    return out or raw
