"""Подготовка текста к синтезу речи.

Синтезатор читает ровно то, что получил, поэтому качество речи сильно
зависит от текста. Здесь:

1. Пунктуация приводится к той, что синтезатор превращает в паузы и интонацию:
   тире и скобки становятся запятыми, кавычки и разметка убираются,
   у фразы всегда есть финальный знак, иначе интонация "повисает".
2. Словарь произношений: англ. названия кириллицей, сокращения целиком.
3. Ударения: в словаре пишутся через "+" перед ударной гласной ("зам+ок"),
   для каждого движка переводятся в его формат.

Свой словарь: ~/.friday/pronunciations.json, например
    {"замок": "зам+ок", "Aqara": "Ак+ара", "Алматы": "Алмат+ы"}
Он дополняет и перекрывает встроенный.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Literal

from friday.config import settings

log = logging.getLogger(__name__)

StressFormat = Literal["acute", "plus", "none"]

VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯaeiouyAEIOUY"
COMBINING_ACUTE = "́"

# Ключи регистронезависимые, заменяются целыми словами.
DEFAULT_PRONUNCIATIONS: dict[str, str] = {
    # техника и сервисы
    "Home Assistant": "хоум ассист+ант",
    "HomePod mini": "хоум под мини",
    "HomePod": "хоум под",
    "HomeKit": "хоум кит",
    "AirPlay": "эйрпл+ей",
    "Apple": "+эппл",
    "iPhone": "айф+он",
    "iPad": "айп+ад",
    "MacBook": "макб+ук",
    "Mac": "мак",
    "macOS": "мак о эс",
    "Siri": "с+ири",
    "Matter": "м+эттер",
    "Zigbee": "з+игби",
    "Aqara": "ак+ара",
    "Wi-Fi": "вайф+ай",
    "WiFi": "вайф+ай",
    "Bluetooth": "блют+ус",
    "USB": "ю эс б+и",
    "Claude": "клод",
    "Anthropic": "антр+опик",
    "ElevenLabs": "+илевен лэбс",
    "Google": "гугл",
    "YouTube": "ют+уб",
    "Telegram": "телегр+ам",
    "Spotify": "спот+ифай",
    "Netflix": "н+етфликс",
    "GitHub": "г+итхаб",
    "Python": "п+айтон",
    "Django": "дж+анго",
    "API": "эй пи +ай",
    "OK": "ок+ей",
    "ok": "ок+ей",
    # частые сокращения
    "т.е.": "то есть",
    "т.к.": "так как",
    "и т.д.": "и так далее",
    "и т.п.": "и тому подобное",
    "в т.ч.": "в том числе",
    "т.н.": "так называемый",
    "напр.": "например",
    "км/ч": "километров в час",
    "м/с": "метров в секунду",
    "мин.": "минут",
    "сек.": "секунд",
    "ч.": "часов",
    # слова, где синтезатор часто ошибается с ударением
    "звонит": "звон+ит",
    "звонишь": "звон+ишь",
    "включит": "включ+ит",
    "включишь": "включ+ишь",
    "облегчить": "облегч+ить",
    "договор": "догов+ор",
    "торты": "т+орты",
    "кухонный": "к+ухонный",
    "щавель": "щав+ель",
}


@lru_cache(maxsize=1)
def load_pronunciations() -> dict[str, str]:
    rules = dict(DEFAULT_PRONUNCIATIONS)
    path = settings.data_dir / "pronunciations.json"
    if path.exists():
        try:
            rules.update(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            log.warning("Не удалось прочитать %s: %s", path, exc)
    return rules


@lru_cache(maxsize=4)
def _compile(rules_items: tuple[tuple[str, str], ...]) -> list[tuple[re.Pattern[str], str]]:
    compiled = []
    # длинные ключи первыми, чтобы "HomePod mini" победил "HomePod"
    for key, value in sorted(rules_items, key=lambda kv: -len(kv[0])):
        left = r"(?<![\w])" if key[0].isalnum() else ""
        right = r"(?![\w])" if key[-1].isalnum() else ""
        compiled.append((re.compile(left + re.escape(key) + right, re.IGNORECASE), value))
    return compiled


def apply_pronunciations(text: str, rules: dict[str, str] | None = None) -> str:
    rules = load_pronunciations() if rules is None else rules
    for pattern, value in _compile(tuple(rules.items())):
        text = pattern.sub(value, text)
    return text


def render_stress(text: str, fmt: StressFormat) -> str:
    """Переводит "+" перед ударной гласной в формат движка.
    acute: знак ударения после гласной (ElevenLabs), plus: как есть (Silero), none: убрать."""
    pattern = re.compile(rf"\+([{VOWELS}])")
    if fmt == "plus":
        return text
    if fmt == "acute":
        return pattern.sub(lambda m: m.group(1) + COMBINING_ACUTE, text)
    return pattern.sub(r"\1", text)


_MARKDOWN = [
    (re.compile(r"```.*?```", re.DOTALL), " "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__"), lambda m: m.group(1) or m.group(2)),
    (re.compile(r"(?<!\w)[*_]([^*_]+)[*_](?!\w)"), r"\1"),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    (re.compile(r"https?://\S+"), ""),
]


def normalize_punctuation(text: str) -> str:
    for pattern, repl in _MARKDOWN:
        text = pattern.sub(repl, text)

    # пункты списков превращаем в отдельные фразы
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip() for line in text.splitlines()]
    lines = [ln if re.search(r"[.!?…:,]$", ln) else ln + "." for ln in lines if ln]
    text = " ".join(lines)

    text = re.sub(r"\s*\(([^)]*)\)", r", \1,", text)  # скобки -> пауза запятыми
    text = re.sub(r"\s+[—–-]\s+", ", ", text)  # тире между словами -> пауза
    text = re.sub(r"[«»\"“”„]", "", text)
    text = text.replace(";", ",").replace("...", "…")
    text = re.sub(r"[!?]{2,}", lambda m: m.group()[0], text)

    text = re.sub(r"\s+([,.!?…:])", r"\1", text)
    text = re.sub(r",\s*([.!?…])", r"\1", text)  # ", ." -> "."
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"([,.!?…:])(?=[^\s\d,.!?…:])", r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")

    if text and text[-1] not in ".!?…":
        text += "."
    return text


def prepare_for_speech(text: str, stress: StressFormat = "acute") -> str:
    # словарь до пунктуации: иначе "т.е." успеет превратиться в "т. е."
    text = apply_pronunciations(text)
    text = normalize_punctuation(text)
    return render_stress(text, stress)
