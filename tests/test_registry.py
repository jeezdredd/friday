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
