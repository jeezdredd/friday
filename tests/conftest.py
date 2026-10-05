import pytest

from friday.config import settings
from friday.location import get_location


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Никаких походов в сеть и записи в настоящий ~/.friday во время тестов."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "home_lat", "")
    monkeypatch.setattr(settings, "home_lon", "")
    monkeypatch.setattr(settings, "timezone", "UTC")

    def no_network():
        raise RuntimeError("network disabled in tests")

    monkeypatch.setattr("friday.location.detect_by_ip", no_network)
    get_location.cache_clear()
    yield
    get_location.cache_clear()
