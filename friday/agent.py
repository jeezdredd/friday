"""Мозг ассистента: диалог с Claude и цикл вызова инструментов."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from anthropic import Anthropic

from friday.config import settings
from friday.location import get_location, get_timezone
from friday.prompts import BASE_PROMPT
from friday.tools import ToolRegistry, load_all
from friday.tools.memory import load_facts

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8


def build_system_prompt(now: datetime | None = None) -> str:
    tz = get_timezone()
    now = now or datetime.now(ZoneInfo(tz))
    context = [f"- Сейчас: {now.strftime('%Y-%m-%d %H:%M, %A')} ({tz})"]
    if settings.user_name:
        context.append(f"- Пользователь: {settings.user_name}")
    loc = get_location()
    if loc and loc.describe():
        context.append(f'- Дом: {loc.describe()}. Погода, время и "здесь" по умолчанию относятся к этому месту.')

    parts = [BASE_PROMPT, "# Контекст\n" + "\n".join(context)]
    facts = load_facts()
    if facts:
        parts.append("# Что ты знаешь о пользователе\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


class Agent:
    def __init__(
        self,
        client: Any | None = None,
        registry: ToolRegistry | None = None,
        on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = client or Anthropic(api_key=settings.anthropic_api_key or None)
        self.registry = registry or load_all()
        self.history: list[dict[str, Any]] = []
        self.on_tool_call = on_tool_call

    def reset(self) -> None:
        self.history.clear()

    def ask(self, text: str) -> str:
        self.history.append({"role": "user", "content": text})
        self._trim_history()

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=settings.model,
                max_tokens=settings.max_tokens,
                system=build_system_prompt(),
                tools=self.registry.schemas(),
                messages=self.history,
            )
            content = [block.model_dump(exclude_none=True) for block in response.content]
            self.history.append({"role": "assistant", "content": content})

            if response.stop_reason != "tool_use":
                return _text_of(content)

            tool_results = []
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                name, args = block["name"], block.get("input", {})
                if self.on_tool_call:
                    self.on_tool_call(name, args)
                output, is_error = self.registry.execute(name, args)
                log.info("tool %s(%s) -> %s", name, args, output[:200])
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": output,
                        "is_error": is_error,
                    }
                )
            self.history.append({"role": "user", "content": tool_results})

        return "Что-то я запуталась в действиях, давай попробуем ещё раз."

    def _trim_history(self) -> None:
        """Обрезает старые сообщения, не разрывая пары tool_use / tool_result:
        история всегда начинается с обычной реплики пользователя."""
        while len(self.history) > settings.max_history:
            self.history.pop(0)
            while self.history and not _is_plain_user(self.history[0]):
                self.history.pop(0)


def _is_plain_user(msg: dict[str, Any]) -> bool:
    return msg["role"] == "user" and isinstance(msg["content"], str)


def _text_of(content: list[dict[str, Any]]) -> str:
    return " ".join(b["text"] for b in content if b.get("type") == "text").strip()
