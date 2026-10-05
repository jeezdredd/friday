from typing import Annotated, Literal

import pytest

from friday.tools import ToolRegistry, load_all
from friday.tools.registry import build_schema


def test_schema_from_type_hints():
    def f(
        name: Annotated[str, "Имя"],
        count: int = 3,
        mode: Literal["a", "b"] = "a",
        level: float | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """doc"""

    schema = build_schema(f)
    props = schema["properties"]
    assert schema["required"] == ["name"]
    assert props["name"] == {"type": "string", "description": "Имя"}
    assert props["count"] == {"type": "integer", "default": 3}
    assert props["mode"]["enum"] == ["a", "b"]
    assert props["level"] == {"type": "number"}
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}


def test_tool_without_docstring_rejected():
    reg = ToolRegistry()

    def nodoc():
        pass

    with pytest.raises(ValueError):
        reg.register(nodoc)


def test_execute_catches_errors():
    reg = ToolRegistry()

    def boom() -> str:
        """Падает."""
        raise RuntimeError("nope")

    reg.register(boom)
    out, is_error = reg.execute("boom", {})
    assert is_error and "nope" in out
    out, is_error = reg.execute("missing", {})
    assert is_error


def test_builtin_tools_load():
    names = {t.name for t in load_all().all()}
    assert {"set_light", "list_lights", "get_datetime", "get_weather", "remember"} <= names


def test_unavailable_tools_hidden_from_model():
    reg = ToolRegistry()
    enabled = {"on": False}

    def lamp() -> str:
        """Лампа."""
        return "ok"

    def clock() -> str:
        """Часы."""
        return "ok"

    reg.register(lamp, available=lambda: enabled["on"])
    reg.register(clock)
    assert [s["name"] for s in reg.schemas()] == ["clock"]
    enabled["on"] = True
    assert [s["name"] for s in reg.schemas()] == ["lamp", "clock"]


def test_home_tools_hidden_without_ha_token(monkeypatch):
    from friday.config import settings

    reg = load_all()
    monkeypatch.setattr(settings, "ha_token", "")
    assert not {"set_light", "list_lights", "get_light_state"} & {s["name"] for s in reg.schemas()}
    monkeypatch.setattr(settings, "ha_token", "token")
    assert {"set_light", "list_lights"} <= {s["name"] for s in reg.schemas()}


def test_expected_errors_logged_without_traceback(caplog):
    from friday.tools import ToolError

    reg = ToolRegistry()

    def not_configured() -> str:
        """Не настроено."""
        raise ToolError("HA_TOKEN не задан")

    def bug() -> str:
        """Баг."""
        raise KeyError("x")

    reg.register(not_configured)
    reg.register(bug)

    out, err = reg.execute("not_configured", {})
    assert err and out == "Ошибка: HA_TOKEN не задан"
    assert all(r.exc_info is None for r in caplog.records)

    caplog.clear()
    out, err = reg.execute("bug", {})
    assert err and "KeyError" in out
    assert any(r.exc_info for r in caplog.records)  # настоящий баг виден с трейсбеком
