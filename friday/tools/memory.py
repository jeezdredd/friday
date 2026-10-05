"""Долговременная память: факты о пользователе, которые переживают перезапуск.

Хранится локально в FRIDAY_DATA_DIR/memory.json (по умолчанию ~/.friday),
вне репозитория. Факты подмешиваются в системный промпт агентом.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from friday.config import settings
from friday.tools import tool


def _path() -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / "memory.json"


def load_facts() -> list[str]:
    p = _path()
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _save(facts: list[str]) -> None:
    _path().write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")


@tool
def remember(fact: Annotated[str, "Короткий факт о пользователе или его доме"]) -> str:
    """Запомнить факт надолго (предпочтения, имена, привычки). Используй, когда пользователь просит запомнить."""
    facts = load_facts()
    if fact not in facts:
        facts.append(fact)
        _save(facts)
    return "Запомнила"


@tool
def forget(fact_substring: Annotated[str, "Часть текста факта, который нужно удалить"]) -> str:
    """Удалить запомненный факт."""
    facts = load_facts()
    kept = [f for f in facts if fact_substring.lower() not in f.lower()]
    _save(kept)
    removed = len(facts) - len(kept)
    return f"Удалено фактов: {removed}"
