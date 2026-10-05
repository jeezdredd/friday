"""Базовые инструменты: время, погода."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

import httpx

from friday.config import settings
from friday.tools import tool

_WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "лёгкая морось",
    53: "морось",
    55: "сильная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежная крупа",
    80: "ливень",
    81: "ливень",
    82: "сильный ливень",
    85: "снегопад",
    86: "сильный снегопад",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}


@tool
def get_datetime() -> str:
    """Текущие дата, время и день недели."""
    now = datetime.now(ZoneInfo(settings.timezone))
    return now.strftime("%Y-%m-%d %H:%M, %A") + f" ({settings.timezone})"


@tool
def get_weather(
    days: Annotated[int, "Сколько дней прогноза вернуть, 1-7"] = 1,
) -> dict[str, Any]:
    """Погода сейчас и прогноз на несколько дней для дома пользователя."""
    if not (settings.weather_lat and settings.weather_lon):
        raise ValueError("WEATHER_LAT/WEATHER_LON не заданы в .env")
    resp = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": settings.weather_lat,
            "longitude": settings.weather_lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "timezone": settings.timezone,
            "forecast_days": max(1, min(7, days)),
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    cur = data["current"]
    daily = data["daily"]
    return {
        "now": {
            "temp_c": cur["temperature_2m"],
            "feels_like_c": cur["apparent_temperature"],
            "humidity_pct": cur["relative_humidity_2m"],
            "wind_kmh": cur["wind_speed_10m"],
            "conditions": _WEATHER_CODES.get(cur["weather_code"], str(cur["weather_code"])),
        },
        "forecast": [
            {
                "date": d,
                "min_c": tmin,
                "max_c": tmax,
                "precip_prob_pct": p,
                "conditions": _WEATHER_CODES.get(code, str(code)),
            }
            for d, tmin, tmax, p, code in zip(
                daily["time"],
                daily["temperature_2m_min"],
                daily["temperature_2m_max"],
                daily["precipitation_probability_max"],
                daily["weather_code"],
            )
        ],
    }
