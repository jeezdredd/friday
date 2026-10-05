"""Реестр инструментов.

Чтобы добавить новую возможность ассистенту, достаточно написать функцию
в любом модуле внутри friday/tools/ и повесить на неё декоратор @tool.
JSON-схема для LLM строится автоматически из type hints и docstring.

    from typing import Annotated
    from friday.tools import tool

    @tool
    def coffee(strength: Annotated[int, "Крепость 1-5"] = 3) -> str:
        '''Сварить кофе в умной кофеварке.'''
        ...
"""

from __future__ import annotations

import inspect
import json
import logging
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, get_args, get_origin

log = logging.getLogger(__name__)

_PRIMITIVES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    input_schema: dict[str, Any]
    # Что сказать голосом, пока инструмент работает и модель думает над ответом.
    # None = случайная общая фраза, "" = молчать (для быстрых действий вроде света).
    filler: str | None = None
    # Показывать ли инструмент модели прямо сейчас. Например, инструменты умного дома
    # не нужны, пока не настроен Home Assistant: иначе модель будет пытаться ими пользоваться.
    available: Callable[[], bool] | None = None
    # Простое действие: если модель написала подтверждение вместе с вызовом и инструмент
    # отработал без ошибки, второй запрос к модели не нужен, подтверждение и есть ответ.
    quick_reply: bool = False

    def is_available(self) -> bool:
        return self.available is None or bool(self.available())

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def run(self, arguments: dict[str, Any]) -> str:
        result = self.func(**arguments)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        filler: str | None = None,
        available: Callable[[], bool] | None = None,
        quick_reply: bool = False,
    ) -> Tool:
        tool_name = name or func.__name__
        if tool_name in self._tools:
            raise ValueError(f"Инструмент {tool_name!r} уже зарегистрирован")
        description = inspect.cleandoc(func.__doc__ or "").strip()
        if not description:
            raise ValueError(f"У инструмента {tool_name!r} нет docstring, LLM не поймёт, зачем он")
        t = Tool(tool_name, description, func, build_schema(func), filler, available, quick_reply)
        self._tools[tool_name] = t
        return t

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def available(self) -> list[Tool]:
        return [t for t in self._tools.values() if t.is_available()]

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.available()]

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Возвращает (результат, is_error). Исключения не пробрасываются наружу,
        а отдаются модели текстом, чтобы она могла сама отреагировать."""
        t = self._tools.get(name)
        if t is None:
            return f"Неизвестный инструмент: {name}", True
        try:
            return t.run(arguments), False
        except Exception as exc:
            if is_expected(exc):
                # ожидаемая ситуация (не настроено, нет разрешения, неверный аргумент): без трейсбека
                log.warning("Tool %s: %s", name, exc)
                return f"Ошибка: {exc}", True
            log.exception("Tool %s failed", name)
            return f"Ошибка: {type(exc).__name__}: {exc}", True


class ToolError(RuntimeError):
    """Ожидаемая ошибка инструмента: текст понятен пользователю, трейсбек не нужен.
    Наследуй от неё ошибки интеграций (не настроено, нет доступа, не найдено)."""


def is_expected(exc: Exception) -> bool:
    return isinstance(exc, ToolError | ValueError)


registry = ToolRegistry()


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    filler: str | None = None,
    available: Callable[[], bool] | None = None,
    quick_reply: bool = False,
):
    """Декоратор: регистрирует функцию как инструмент ассистента.

    filler: фраза, которую Пятница скажет, пока инструмент выполняется.
    available: функция без аргументов; если вернула False, модель инструмент не видит.
    quick_reply: простое действие, подтверждение модели можно озвучить без второго запроса.
    """

    def wrap(f: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(f, name=name, filler=filler, available=available, quick_reply=quick_reply)
        return f

    return wrap(func) if func is not None else wrap


# ---------- построение JSON-схемы из сигнатуры ----------


def build_schema(func: Callable[..., Any]) -> dict[str, Any]:
    hints = typing.get_type_hints(func, include_extras=True)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for pname, param in inspect.signature(func).parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, str)
        prop = _type_to_schema(annotation)
        if param.default is not inspect.Parameter.empty:
            if param.default is not None:
                prop["default"] = param.default
        else:
            required.append(pname)
        properties[pname] = prop

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _type_to_schema(tp: Any) -> dict[str, Any]:
    origin = get_origin(tp)

    # Annotated[T, "описание"]
    if origin is typing.Annotated:
        base, *meta = get_args(tp)
        schema = _type_to_schema(base)
        desc = next((m for m in meta if isinstance(m, str)), None)
        if desc:
            schema["description"] = desc
        return schema

    # Optional[T] / T | None
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _type_to_schema(args[0])
        return {"anyOf": [_type_to_schema(a) for a in args]}

    if origin is Literal:
        values = list(get_args(tp))
        schema = _type_to_schema(type(values[0]))
        schema["enum"] = values
        return schema

    if origin in (list, tuple, set):
        args = get_args(tp)
        item = _type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item}

    if origin is dict or tp is dict:
        return {"type": "object"}

    if tp in _PRIMITIVES:
        return {"type": _PRIMITIVES[tp]}

    return {"type": "string"}
