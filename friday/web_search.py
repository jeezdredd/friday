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


class LocationMode:
    """Насколько подробно передавать местоположение. API поддерживает не все страны:
    на неподдерживаемую возвращает 400, тогда понижаем режим и повторяем запрос."""

    FULL = "full"  # город, регион, страна, таймзона
    NO_COUNTRY = "no_country"  # без кода страны
    NONE = "none"  # без user_location вообще

    ORDER = (FULL, NO_COUNTRY, NONE)

    @classmethod
    def downgrade(cls, mode: str) -> str | None:
        i = cls.ORDER.index(mode)
        return cls.ORDER[i + 1] if i + 1 < len(cls.ORDER) else None


def _mode_path():
    return settings.data_dir / "web_search_location_mode"


def load_location_mode() -> str:
    """Режим, до которого уже понижались раньше: не тратим лишний запрос на каждом старте."""
    try:
        mode = _mode_path().read_text(encoding="utf-8").strip()
    except OSError:
        return LocationMode.FULL
    return mode if mode in LocationMode.ORDER else LocationMode.FULL


def save_location_mode(mode: str) -> None:
    try:
        _mode_path().parent.mkdir(parents=True, exist_ok=True)
        _mode_path().write_text(mode, encoding="utf-8")
    except OSError:
        pass


def tool_definition(location_mode: str = LocationMode.FULL) -> dict[str, Any] | None:
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
    if location_mode != LocationMode.NONE:
        location = user_location(include_country=location_mode == LocationMode.FULL)
        if location:
            definition["user_location"] = location
    return definition


def user_location(include_country: bool = True) -> dict[str, str] | None:
    """Локализует выдачу под дом: курсы, новости, погода в первую очередь местные."""
    loc = get_location()
    if loc is None:
        return None
    data = {"type": "approximate", "timezone": get_timezone()}
    if loc.city:
        data["city"] = loc.city
    if loc.region:
        data["region"] = loc.region
    if include_country and len(loc.country) == 2:  # API ждёт ISO-код страны
        data["country"] = loc.country
    return data


def classify_error(exc: Exception) -> str | None:
    """Что именно API не устроило в инструменте поиска.

    location: не поддерживается местоположение (например, страна), поиск сам по себе работает
    disabled: поиск не включён для организации или ключа
    None: ошибка не про поиск
    """
    text = str(exc).lower()
    if "web_search" not in text and "web search" not in text:
        return None
    if "country" in text or "user_location" in text or "location" in text or "timezone" in text:
        return "location"
    if "not enabled" in text or "disabled" in text or "not available" in text or "not allowed" in text:
        return "disabled"
    return None


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
