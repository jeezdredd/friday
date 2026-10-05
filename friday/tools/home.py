"""Управление умным домом через Home Assistant."""

from __future__ import annotations

from typing import Annotated, Any

from friday.config import settings
from friday.integrations.homeassistant import get_ha
from friday.tools import tool


def _resolve_light(entity_id: str | None) -> str:
    target = entity_id or settings.default_light
    if not target:
        raise ValueError("Не указана лампа и не задан FRIDAY_DEFAULT_LIGHT. Вызови list_lights.")
    return target


def _short_state(s: dict[str, Any]) -> dict[str, Any]:
    attrs = s.get("attributes", {})
    brightness = attrs.get("brightness")
    return {
        "entity_id": s["entity_id"],
        "name": attrs.get("friendly_name"),
        "state": s["state"],
        "brightness_pct": round(brightness / 255 * 100) if brightness is not None else None,
        "color_temp_kelvin": attrs.get("color_temp_kelvin"),
        "rgb_color": attrs.get("rgb_color"),
    }


@tool
def list_lights() -> list[dict[str, Any]]:
    """Список всех ламп в доме с текущим состоянием (вкл/выкл, яркость, цвет)."""
    return [_short_state(s) for s in get_ha().entities("light")]


@tool
def get_light_state(
    entity_id: Annotated[str | None, "entity_id лампы, например light.room. Пусто = лампа по умолчанию"] = None,
) -> dict[str, Any]:
    """Текущее состояние конкретной лампы."""
    return _short_state(get_ha().state(_resolve_light(entity_id)))


@tool
def set_light(
    on: Annotated[bool, "true = включить, false = выключить"],
    entity_id: Annotated[str | None, "entity_id лампы. Пусто = лампа по умолчанию"] = None,
    brightness_pct: Annotated[int | None, "Яркость 1-100"] = None,
    color_temp_kelvin: Annotated[int | None, "Цветовая температура, 2000 тёплый .. 6500 холодный"] = None,
    color_name: Annotated[str | None, "Цвет по названию на английском (red, blue, purple...)"] = None,
    transition: Annotated[float | None, "Плавность перехода в секундах"] = None,
) -> str:
    """Включить, выключить лампу или изменить её яркость и цвет."""
    target = _resolve_light(entity_id)
    data: dict[str, Any] = {"entity_id": target}
    if transition is not None:
        data["transition"] = transition

    if not on:
        get_ha().call_service("light", "turn_off", data)
        return f"{target} выключена"

    if brightness_pct is not None:
        data["brightness_pct"] = max(1, min(100, brightness_pct))
    if color_temp_kelvin is not None:
        data["color_temp_kelvin"] = color_temp_kelvin
    if color_name:
        data["color_name"] = color_name
    get_ha().call_service("light", "turn_on", data)
    return f"{target} включена: {data}"


@tool
def get_entity_state(
    entity_id: Annotated[str, "Любой entity_id из Home Assistant, например sensor.room_temperature"],
) -> dict[str, Any]:
    """Прочитать состояние любого устройства или датчика (температура, влажность, движение и т.д.)."""
    s = get_ha().state(entity_id)
    return {"entity_id": entity_id, "state": s["state"], "attributes": s.get("attributes", {})}


@tool
def list_sensors() -> list[dict[str, Any]]:
    """Список всех датчиков в доме с текущими значениями."""
    return [
        {
            "entity_id": s["entity_id"],
            "name": s["attributes"].get("friendly_name"),
            "state": s["state"],
            "unit": s["attributes"].get("unit_of_measurement"),
        }
        for s in get_ha().entities("sensor")
    ]
