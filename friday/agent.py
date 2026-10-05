"""Мозг ассистента: диалог с Claude и цикл вызова инструментов."""

from __future__ import annotations

import logging
import time
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


def build_context(now: datetime | None = None) -> str:
    """Динамическая часть промпта: время, дом, факты. Меняется, поэтому не кешируется."""
    tz = get_timezone()
    now = now or datetime.now(ZoneInfo(tz))
    context = [f"- Сейчас: {now.strftime('%Y-%m-%d %H:%M, %A')} ({tz})"]
    if settings.user_name:
        context.append(f"- Пользователь: {settings.user_name}")
    loc = get_location()
    if loc and loc.describe():
        context.append(f'- Дом: {loc.describe()}. Погода, время и "здесь" по умолчанию относятся к этому месту.')

    parts = ["# Контекст\n" + "\n".join(context)]
    facts = load_facts()
    if facts:
        parts.append("# Что ты знаешь о пользователе\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


def build_system_prompt(now: datetime | None = None) -> str:
    return BASE_PROMPT + "\n\n" + build_context(now)


def build_system_blocks(now: datetime | None = None) -> list[dict[str, Any]]:
    """Статичная часть (инструменты + базовый промпт) кешируется на стороне API,
    точка кеша стоит до динамического контекста, чтобы смена минуты его не сбрасывала."""
    return [
        {"type": "text", "text": BASE_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": build_context(now)},
    ]


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

        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            started = time.monotonic()
            response = self.client.messages.create(
                model=settings.model,
                max_tokens=settings.max_tokens,
                system=build_system_blocks(),
                tools=self.registry.schemas(),
                messages=self.history,
            )
            _log_llm_timing(round_no, started, response)
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
                started = time.monotonic()
                output, is_error = self.registry.execute(name, args)
                log.info("tool %s(%s) %.2f сек -> %s", name, args, time.monotonic() - started, output[:200])
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


def _log_llm_timing(round_no: int, started: float, response: Any) -> None:
    usage = getattr(response, "usage", None)
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    log.info("LLM раунд %d: %.2f сек, из кеша %s токенов", round_no, time.monotonic() - started, cached)


def _is_plain_user(msg: dict[str, Any]) -> bool:
    return msg["role"] == "user" and isinstance(msg["content"], str)


def _text_of(content: list[dict[str, Any]]) -> str:
    return " ".join(b["text"] for b in content if b.get("type") == "text").strip()
