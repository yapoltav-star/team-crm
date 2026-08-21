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
        "Если сказал «сегодня»/«завтра» — due=today|tomorrow, иначе due=default.\n"
        "Если сказал «добавь комментарий …» — вынеси текст в comment, а из title убери эту часть.\n"
        "В title можно писать короткий артикул: «042 голд», «041 серый» — "
        "система сама развернёт в полный vendorCode; не выдумывай артикулы.\n"
        "Спросить задачи / кто чем занят / у кого что → list_tasks "
        "(who=all для всей команды, who=имя любого сотрудника, who=me для своих). "
        "«задачи Ивана» / «что у Софии» → who=имя.\n"
        "Изменить текст → edit_task.\n"
        "«закрой задачу …» / «заверши» / «отметь сделанной» → complete_task "
        "(задача становится выполненной, НЕ удаляется).\n"
        "«удали задачу …» / «убери» / «снеси» → delete_task.\n"
        "ВАЖНО: закрой ≠ удали. Если сказали закрой/заверши — только complete_task.\n"
        "query = id или часть названия.\n"
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
        action = call.function.name
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
