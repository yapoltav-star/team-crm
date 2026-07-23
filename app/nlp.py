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
            "description": "Создать задачу сотруднику или себе",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Текст задачи"},
                    "assignee": {
                        "type": "string",
                        "description": "me | boss | имя сотрудника из списка",
                    },
                },
                "required": ["title", "assignee"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_tasks",
            "description": "Показать открытые задачи автора",
            "parameters": {"type": "object", "properties": {}},
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
) -> dict[str, Any]:
    names = ", ".join(f"{p['name']} ({p['role']})" for p in people) or "пока никого"
    system = (
        "Ты ассистент CRM в Telegram. Пользователь пишет текстом или голосом.\n"
        f"Автор: {author_name}. Сотрудники: {names}.\n"
        "Создать задачу → tool create_task (assignee=me|boss|имя).\n"
        "Список задач → list_my_tasks. Иначе короткий ответ."
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
