import json
from datetime import UTC, datetime

from friday import location
from friday.agent import build_system_prompt
from friday.config import settings
from friday.location import Location, get_location, get_timezone


def test_detects_once_and_caches(monkeypatch, tmp_path):
    calls = []

    def fake_detect():
        calls.append(1)
        return Location(1.5, 2.5, "Testville", "Region", "TC", "Asia/Tokyo")

    monkeypatch.setattr(location, "detect_by_ip", fake_detect)
    monkeypatch.setattr(settings, "timezone", "")

    assert get_location().city == "Testville"
    assert get_timezone() == "Asia/Tokyo"
    assert json.loads((tmp_path / "location.json").read_text())["lat"] == 1.5

    get_location.cache_clear()
    assert get_location().city == "Testville"
    assert len(calls) == 1  # второй раз взяли из кеша, а не из сети


def test_env_override_wins(monkeypatch):
    monkeypatch.setattr(settings, "home_lat", "10")
    monkeypatch.setattr(settings, "home_lon", "20")
    monkeypatch.setattr(settings, "home_city", "Home")
    loc = get_location()
    assert (loc.lat, loc.lon, loc.city) == (10.0, 20.0, "Home")


def test_no_network_is_not_fatal(monkeypatch):
    monkeypatch.setattr(settings, "timezone", "")
    assert get_location() is None
    assert get_timezone() == "UTC"


def test_prompt_contains_context(monkeypatch):
    monkeypatch.setattr(location, "detect_by_ip", lambda: Location(1, 2, "Testville", "", "TC", "UTC"))
    prompt = build_system_prompt(now=datetime(2026, 1, 2, 9, 30, tzinfo=UTC))
    assert "# Контекст" in prompt
    assert "Testville, TC" in prompt
    assert "2026-01-02 09:30" in prompt
