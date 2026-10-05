"""Где находится дом.

Порядок:
1. HOME_LAT / HOME_LON в .env (ручной override, если IP врёт, например под VPN)
2. Кеш ~/.friday/location.json (дом не переезжает, поэтому определяем один раз)
3. Геолокация по внешнему IP, результат кешируется

Чтобы определить заново, удали кеш: rm ~/.friday/location.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from functools import lru_cache

import httpx

from friday.config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    city: str = ""
    region: str = ""
    country: str = ""
    timezone: str = ""

    def describe(self) -> str:
        return ", ".join(p for p in (self.city, self.region, self.country) if p)


def _cache_path():
    return settings.data_dir / "location.json"


def _from_ipinfo(client: httpx.Client) -> Location:
    d = client.get("https://ipinfo.io/json").raise_for_status().json()
    lat, lon = (float(x) for x in d["loc"].split(","))
    return Location(lat, lon, d.get("city", ""), d.get("region", ""), d.get("country", ""), d.get("timezone", ""))


def _from_ipapi(client: httpx.Client) -> Location:
    d = client.get("https://ipapi.co/json/").raise_for_status().json()
    return Location(
        float(d["latitude"]),
        float(d["longitude"]),
        d.get("city", ""),
        d.get("region", ""),
        d.get("country_name", ""),
        d.get("timezone", ""),
    )


def detect_by_ip() -> Location:
    errors = []
    with httpx.Client(timeout=8) as client:
        for provider in (_from_ipinfo, _from_ipapi):
            try:
                return provider(client)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider.__name__}: {exc}")
    raise RuntimeError("Не удалось определить местоположение: " + "; ".join(errors))


@lru_cache(maxsize=1)
def get_location() -> Location | None:
    if settings.home_lat and settings.home_lon:
        return Location(float(settings.home_lat), float(settings.home_lon), settings.home_city)

    path = _cache_path()
    if path.exists():
        try:
            return Location(**json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            log.warning("Битый кеш местоположения, определяю заново")

    try:
        loc = detect_by_ip()
    except RuntimeError as exc:
        log.warning("%s", exc)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(loc), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Дом определён: %s", loc.describe())
    return loc


def get_timezone() -> str:
    """Таймзона: явная из .env, иначе из местоположения, иначе UTC."""
    if settings.timezone:
        return settings.timezone
    loc = get_location()
    return (loc and loc.timezone) or "UTC"
