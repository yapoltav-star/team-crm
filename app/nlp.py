from __future__ import annotations

import io
import json
import logging
from datetime import date
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "Создать задачу сотруднику, группе или всей команде. "
                "Если названо ИМЯ сразу после «поставь задачу Софии» — assignee=это имя. "
                "Имена дальше в тексте («согласовать с Дилей и Ярославом») — НЕ assignees. "
                "«всем» / «всех» без проекта — assignee=all. "
                "«менеджерам ПВС» / «складу на ПВС» — assignee вида «ПВС/менеджер» "
                "(проект/роль), НЕ all. "
                "Голое слово проекта в описании («бренд ПВС») — НЕ назначение группе."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": (
                            "Текст задачи БЕЗ адресата (без «Софии», без «менеджерам ПВС»). "
                            "Бренд/проект в сути задачи оставляй («бренд ПВС», «на Озон»)."
                        ),
                    },
                    "assignee": {
                        "type": "string",
                        "description": (
                            "me | boss | all | имя сотрудника | проект/роль. "
                            "Примеры: «София», «ПВС/менеджер», «project:ПВС». "
                            "Имя важнее проекта. Если адресат не указан — me. "
                            "all — ТОЛЬКО если сказали всем/всех "
                            "без названия проекта как адресата"
                        ),
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "Срок задачи. "
                            "today — сегодня; tomorrow — завтра; "
                            "YYYY-MM-DD — конкретная дата («на 10 сентября» → дату года); "
                            "default — только если срок НЕ назвали (тогда +3 дня)"
                        ),
                    },
                    "comment": {
                        "type": "string",
                        "description": (
                            "Текст комментария, если сказал "
                            "«добавь комментарий …» / «комментарий: …». "
                            "Иначе не заполняй."
                        ),
                    },
                },
                "required": ["title", "assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "Показать открытые задачи. "
                "who=me — мои; who=all — у всей команды (кто чем занят); "
                "who=<имя> — задачи конкретного человека. "
                "Используй для вопросов: у кого какие задачи, что у Ивана, статус команды."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "who": {
                        "type": "string",
                        "description": "me | all | имя сотрудника",
                    },
                },
                "required": ["who"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_tasks",
            "description": "Синоним list_tasks с who=me",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_task",
            "description": "Изменить текст открытой задачи (по номеру или по фрагменту названия)",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "id задачи или часть названия",
                    },
                    "title": {"type": "string", "description": "Новый текст задачи"},
                    "who": {
                        "type": "string",
                        "description": "me|all|имя — где искать, по умолчанию all для владельца",
                    },
                },
                "required": ["query", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": (
                "Закрыть / завершить задачу как выполненную (статус done). "
                "Для фраз: закрой, заверши, сделай выполненной, отметь сделанной, "
                "готово по задаче. НЕ удаляет задачу."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "id задачи или часть названия",
                    },
                    "who": {
                        "type": "string",
                        "description": "me|all|имя — где искать",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": (
                "Удалить задачу насовсем. Только если явно сказали «удали/убери/снеси». "
                "«Закрой/заверши» — это НЕ удаление, для них complete_task."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "id задачи или часть названия",
                    },
                    "who": {
                        "type": "string",
                        "description": "me|all|имя — где искать",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "help",
            "description": "Краткая справка",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _client(settings: Settings) -> AsyncOpenAI:
    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if str(settings.openai_base_url).strip():
        kwargs["base_url"] = str(settings.openai_base_url).strip()
    return AsyncOpenAI(**kwargs)


def _model_name(settings: Settings) -> str:
    return (settings.openai_model or "gpt-5.6-terra").strip()


def _uses_responses_api(model: str) -> bool:
    """gpt-5.4+ + tools → Responses API; иначе chat.completions."""
    m = (model or "").lower().strip()
    if m.startswith(("gpt-5.6", "gpt-5.5", "gpt-5.4")):
        return True
    if m in {"gpt-5.6", "gpt-5.5", "gpt-5.4", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}:
        return True
    return False


def _responses_tools() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in TOOLS:
        fn = t["function"]
        out.append(
            {
                "type": "function",
                "name": fn["name"],
                "description": fn["description"],
                "parameters": fn["parameters"],
            }
        )
    return out


def _build_system(
    *,
    author_name: str,
    people: list[dict[str, str]],
    is_owner: bool,
    job_title: str,
    team_group: str,
) -> str:
    names = (
        ", ".join(
            f"{p['name']} (доступ:{p.get('role')}, роль:{p.get('job_title') or '—'}, "
            f"проект:{p.get('team_group') or '—'})"
            for p in people
        )
        or "пока никого"
    )
    jt = (job_title or "").strip().lower().replace("ё", "е")
    if is_owner:
        role = "владелец (видит всех сотрудников)"
    elif jt == "рук":
        role = "рук (видит всех сотрудников, как владелец)"
    elif jt == "партнер":
        role = (
            f"партнёр проекта «{team_group or '—'}» "
            "(видит только сотрудников своего проекта; list_tasks who=all = свой проект)"
        )
    else:
        role = "сотрудник (свои задачи; чужие — только если есть доступ)"
    today = date.today()
    return (
        "Ты ассистент task-CRM в Telegram. Пользователь пишет текстом или голосом.\n"
        f"Сегодня: {today.isoformat()} (год {today.year}).\n"
        f"Автор: {author_name} — {role}. Сотрудники в зоне видимости: {names}.\n"
        "Создать задачу → create_task.\n"
        "«поставь задачу Софии … согласовать с Дилей» → assignee=ТОЛЬКО София. "
        "Имена в тексте задачи («с Дилей», «и Ярославом») — НЕ исполнители.\n"
        "Исполнитель — только то, что сразу после «поставь/назначь задачу».\n"
        "Если адресат не назван — assignee=me (задача себе).\n"
        "«поставь задачу всем» без проекта → assignee=all.\n"
        "«поставь задачу Софии … бренд ПВС» → assignee=София, "
        "ПВС в title оставить, НЕ назначать всей группе ПВС.\n"
        "«менеджерам ПВС» / «поддержке ПВС» / «складу на ПВС» / «всем на ПВС» → "
        "assignee=«ПВС/менеджер» (или другая роль / project:ПВС), НЕ all.\n"
        "Голое упоминание проекта в тексте бренда — не аудитория.\n"
        "Если сказал «сегодня»/«завтра» — due=today|tomorrow. "
        "Если назвал дату («на 10 сентября», «до 5.10», «к 12 ноября») — "
        f"due=YYYY-MM-DD (год {today.year}, если дата уже прошла — следующий). "
        "Иначе due=default.\n"
        "Если сказал «добавь комментарий …» — вынеси текст в comment, а из title убери эту часть.\n"
        "В title можно писать короткий артикул: «042 голд», «041 серый» — "
        "система сама развернёт в полный vendorCode; не выдумывай артикулы.\n"
        "Спросить задачи / кто чем занят / у кого что / задачи проекта → list_tasks "
        "(who=all в зоне видимости, who=имя из списка выше, who=me для своих).\n"
        "Изменить текст → edit_task.\n"
        "«закрой задачу …» / «заверши» / «отметь сделанной» → complete_task "
        "(задача становится выполненной, НЕ удаляется).\n"
        "«удали задачу …» / «убери» / «снеси» → delete_task.\n"
        "ВАЖНО: закрой ≠ удали. Если сказали закрой/заверши — только complete_task.\n"
        "query = id или часть названия.\n"
        "Не выдумывай задачи — только вызывай tool, данные подтянет система.\n"
        "Если намерение неочевидно — короткий уточняющий вопрос, без tool.\n"
        "Иначе короткий ответ."
    )


def _finalize_action(text: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
    low = (text or "").lower().replace("ё", "е")
    close_words = (
        "закрой",
        "закройте",
        "заверши",
        "завершите",
        "закрыть",
        "завершить",
        "отметь сделан",
        "отметь выполн",
        "сделай выполнен",
    )
    delete_words = ("удали", "удалите", "убери", "уберите", "снеси", "сноси")
    wants_close = any(w in low for w in close_words)
    wants_delete = any(w in low for w in delete_words)
    # страховка: «закрой» никогда не должно стать удалением
    if action == "delete_task" and wants_close and not wants_delete:
        action = "complete_task"
    return {"action": action, **args}


async def _parse_via_responses(
    client: AsyncOpenAI,
    *,
    model: str,
    system: str,
    text: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    effort = (reasoning_effort or "low").strip().lower() or "low"
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": [{"role": "user", "content": text}],
        "tools": _responses_tools(),
        "tool_choice": "auto",
        "reasoning": {"effort": effort},
    }
    response = await client.responses.create(**kwargs)
    for item in response.output or []:
        if getattr(item, "type", None) != "function_call":
            continue
        try:
            args = json.loads(getattr(item, "arguments", None) or "{}")
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return _finalize_action(text, str(item.name), args)
    reply = (getattr(response, "output_text", None) or "").strip()
    if not reply:
        for item in response.output or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) in {"output_text", "text"}:
                    reply = (getattr(part, "text", None) or "").strip()
                    if reply:
                        break
            if reply:
                break
    return {"action": "chat", "reply": reply or "Не понял."}


async def _parse_via_chat(
    client: AsyncOpenAI,
    *,
    model: str,
    system: str,
    text: str,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "tools": TOOLS,
        "tool_choice": "auto",
    }
    # reasoning-модели (gpt-5*) не принимают temperature ≠ default
    m = model.lower()
    if not m.startswith(("gpt-5", "o1", "o3", "o4")):
        kwargs["temperature"] = 0.1
    response = await client.chat.completions.create(**kwargs)
    msg = response.choices[0].message
    if msg.tool_calls:
        call = msg.tool_calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return _finalize_action(text, call.function.name, args)
    return {"action": "chat", "reply": (msg.content or "Не понял.").strip()}


async def parse_intent(
    settings: Settings,
    *,
    text: str,
    author_name: str,
    people: list[dict[str, str]],
    is_owner: bool = False,
    job_title: str = "",
    team_group: str = "",
) -> dict[str, Any]:
    system = _build_system(
        author_name=author_name,
        people=people,
        is_owner=is_owner,
        job_title=job_title,
        team_group=team_group,
    )
    client = _client(settings)
    model = _model_name(settings)
    try:
        if _uses_responses_api(model):
            return await _parse_via_responses(
                client,
                model=model,
                system=system,
                text=text,
                reasoning_effort=str(settings.openai_reasoning_effort or "low"),
            )
        return await _parse_via_chat(client, model=model, system=system, text=text)
    except Exception:
        logger.exception("parse_intent failed model=%s", model)
        raise


async def transcribe_voice(settings: Settings, ogg_bytes: bytes) -> str:
    client = _client(settings)
    bio = io.BytesIO(ogg_bytes)
    bio.name = "voice.ogg"
    model = (settings.openai_transcribe_model or "gpt-4o-mini-transcribe").strip()
    result = await client.audio.transcriptions.create(
        model=model,
        file=bio,
        language="ru",
    )
    return (result.text or "").strip()
