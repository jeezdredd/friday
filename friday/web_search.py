"""Поиск в интернете через серверный инструмент Anthropic.

Поиск выполняет сам API внутри запроса к модели: отдельного ключа и кода
выполнения нет, оплата $10 за 1000 поисков плюс токены результатов.
Документация: https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool

В консоли Anthropic поиск должен быть включён для организации, иначе API
вернёт 400. В этом случае агент отключает поиск и продолжает работать без него.
"""

from __future__ import annotations

from typing import Any

from friday.config import settings
from friday.location import get_location, get_timezone

TOOL_NAME = "web_search"


def tool_definition() -> dict[str, Any] | None:
    if not settings.web_search:
        return None
    definition: dict[str, Any] = {
        "type": settings.web_search_tool,
        "name": TOOL_NAME,
        "max_uses": settings.web_search_max_uses,
    }
    if settings.web_search_tool >= "web_search_20260209":
        # Без динамической фильтрации через выполнение кода: для голоса важнее скорость
        definition["allowed_callers"] = ["direct"]
    location = user_location()
    if location:
        definition["user_location"] = location
    return definition


def user_location() -> dict[str, str] | None:
    """Локализует выдачу под дом: курсы, новости, погода в первую очередь местные."""
    loc = get_location()
    if loc is None:
        return None
    data = {"type": "approximate", "timezone": get_timezone()}
    if loc.city:
        data["city"] = loc.city
    if loc.region:
        data["region"] = loc.region
    if len(loc.country) == 2:  # API ждёт ISO-код страны
        data["country"] = loc.country
    return data


def is_disabled_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "web search" in text or "web_search" in text


# ---------- уплотнение истории ----------

_SERVER_BLOCKS = {"server_tool_use", "web_search_tool_result"}


def compact_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Выкидывает из завершённого хода результаты поиска и цитаты.

    Результаты поиска считаются входными токенами в каждом следующем запросе,
    а голосовому ассистенту из прошлых ходов нужен только сказанный текст.
    Пары tool_use / tool_result наших инструментов не трогаются.
    """
    compacted = []
    for msg in messages:
        if msg["role"] != "assistant" or isinstance(msg["content"], str):
            compacted.append(msg)
            continue
        blocks: list[dict[str, Any]] = []
        for block in msg["content"]:
            if block.get("type") in _SERVER_BLOCKS:
                continue
            if block.get("type") == "text":
                # цитаты режут ответ на куски, склеиваем обратно в один блок
                if blocks and blocks[-1].get("type") == "text":
                    blocks[-1] = {"type": "text", "text": blocks[-1]["text"] + block["text"]}
                    continue
                block = {"type": "text", "text": block["text"]}
            blocks.append(block)
        if blocks:
            compacted.append({"role": "assistant", "content": blocks})
    return compacted
