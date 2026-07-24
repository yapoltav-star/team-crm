from __future__ import annotations

import io
import json
import logging
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
                "«всем» / «всех» без проекта — assignee=all. "
                "«менеджерам ПВС» / «складу на ПВС» — assignee вида «ПВС/менеджер» "
                "(проект/роль), НЕ all."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Текст задачи БЕЗ адресата (без «менеджерам ПВС»)",
                    },
                    "assignee": {
                        "type": "string",
                        "description": (
                            "me | boss | all | имя | проект/роль. "
                            "Примеры: «ПВС/менеджер», «ПВС/склад», «project:ПВС». "
                            "all — ТОЛЬКО если сказали всем/всех без названия проекта"
                        ),
                    },
                    "due": {
                        "type": "string",
                        "description": (
                            "today — если сказал сегодня; "
                            "tomorrow — завтра; "
                            "default — если срок не уточнял (будет +3 дня)"
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
            "name": "delete_task",
            "description": "Удалить открытую задачу (по номеру или фрагменту названия)",
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


async def parse_intent(
    settings: Settings,
    *,
    text: str,
    author_name: str,
    people: list[dict[str, str]],
    is_owner: bool = False,
) -> dict[str, Any]:
    names = (
        ", ".join(
            f"{p['name']} (доступ:{p.get('role')}, роль:{p.get('job_title') or '—'}, "
            f"проект:{p.get('team_group') or '—'})"
            for p in people
        )
        or "пока никого"
    )
    role = "владелец (видит всю команду)" if is_owner else "сотрудник (свои задачи + можно спросить по имени)"
    system = (
        "Ты ассистент task-CRM в Telegram. Пользователь пишет текстом или голосом.\n"
        f"Автор: {author_name} — {role}. Сотрудники: {names}.\n"
        "Создать задачу → create_task.\n"
        "«поставь задачу всем» без проекта → assignee=all.\n"
        "«менеджерам ПВС» / «поддержке ПВС» / «складу на ПВС» → assignee=«ПВС/менеджер» "
        "(или другая роль), НЕ all. В title только суть задачи.\n"
        "Если сказал «сегодня»/«завтра» — due=today|tomorrow, иначе due=default.\n"
        "Если сказал «добавь комментарий …» — вынеси текст в comment, а из title убери эту часть.\n"
        "В title можно писать короткий артикул: «042 голд», «041 серый» — "
        "система сама развернёт в полный vendorCode; не выдумывай артикулы.\n"
        "Спросить задачи / кто чем занят / у кого что → list_tasks "
        "(who=all для всей команды, who=имя, who=me для своих).\n"
        "Изменить текст → edit_task. Удалить → delete_task "
        "(query = id или часть названия).\n"
        "Не выдумывай задачи — только вызывай tool, данные подтянет система.\n"
        "Иначе короткий ответ."
    )
    client = _client(settings)
    response = await client.chat.completions.create(
        model=settings.openai_model or "gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        tools=TOOLS,
        tool_choice="auto",
        temperature=0.1,
    )
    msg = response.choices[0].message
    if msg.tool_calls:
        call = msg.tool_calls[0]
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        return {"action": call.function.name, **args}
    return {"action": "chat", "reply": (msg.content or "Не понял.").strip()}


async def transcribe_voice(settings: Settings, ogg_bytes: bytes) -> str:
    client = _client(settings)
    bio = io.BytesIO(ogg_bytes)
    bio.name = "voice.ogg"
    result = await client.audio.transcriptions.create(
        model="whisper-1",
        file=bio,
        language="ru",
    )
    return (result.text or "").strip()
