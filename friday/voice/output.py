"""Единая точка вывода речи.

Всё, что Пятница говорит (ответы, заполнители, напоминания), идёт через VoiceOutput:
- одна блокировка, поэтому напоминание не заговорит поверх ответа;
- заполнитель ("Секунду, уточняю") играет в фоне, пока работают инструменты и модель,
  а основной ответ дожидается его окончания, чтобы не наложиться.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Iterable

from friday.config import settings
from friday.tools import ToolRegistry

log = logging.getLogger(__name__)

# {address} подставляется из настроек (FRIDAY_ADDRESS)
FILLER_TEMPLATES = (
    "Секунду.",
    "Секунду, {address}.",
    "Уже проверяю.",
    "Сейчас выясню.",
    "Запрашиваю данные.",
    "Минуту.",
)
ACK_TEMPLATES = ("Да, {address}?", "Слушаю.", "Да?", "Слушаю, {address}.")
# Фразы для инструментов, которых нет в реестре (серверные инструменты API)
EXTRA_FILLER_TEMPLATES = {"web_search": "Ищу в сети."}
GREETING_TEMPLATES = {
    "night": "Доброй ночи, {address}. Системы в норме, я на связи.",
    "morning": "Доброе утро, {address}. Системы в норме, я на связи.",
    "day": "Добрый день, {address}. Системы в норме, я на связи.",
    "evening": "Добрый вечер, {address}. Системы в норме, я на связи.",
}


def _fill(templates, address: str):
    if isinstance(templates, dict):
        return {k: v.format(address=address) for k, v in templates.items()}
    return tuple(t.format(address=address) for t in templates)


def part_of_day(hour: int) -> str:
    if hour < 5:
        return "night"
    if hour < 12:
        return "morning"
    if hour < 18:
        return "day"
    return "evening"


GENERIC_FILLERS = _fill(FILLER_TEMPLATES, settings.address)
ACK_PHRASES = _fill(ACK_TEMPLATES, settings.address)
EXTRA_FILLERS = _fill(EXTRA_FILLER_TEMPLATES, settings.address)
GREETINGS = _fill(GREETING_TEMPLATES, settings.address)
SHORT_PHRASES = ACK_PHRASES  # обратная совместимость


class VoiceOutput:
    def __init__(self, speaker, registry: ToolRegistry | None = None, rng: random.Random | None = None):
        self.speaker = speaker
        self.registry = registry
        self._lock = threading.RLock()
        self._filler_thread: threading.Thread | None = None
        self._filler_used = False
        self._rng = rng or random.Random()
        self._last_generic = ""

    # ---------- основная речь ----------

    def speak(self, text: str) -> None:
        self.wait_filler()
        with self._lock:
            self.speaker.speak(text)

    def ack(self) -> None:
        """Отклик на обращение без команды: "Да, босс?", "Слушаю." Не повторяется подряд."""
        choices = [p for p in ACK_PHRASES if p != getattr(self, "_last_ack", "")] or list(ACK_PHRASES)
        self._last_ack = self._rng.choice(choices)
        self.speak_short(self._last_ack)

    def greet(self, hour: int) -> None:
        self.speak_short(GREETINGS[part_of_day(hour)])

    def speak_short(self, text: str) -> None:
        """Короткие повторяющиеся фразы ("Да?") из кеша, если движок умеет кешировать."""
        with self._lock:
            self._speak_cached(text)

    # ---------- заполнители ----------

    def begin_request(self) -> None:
        """Вызывать перед каждым запросом к агенту: заполнитель звучит не больше раза за запрос."""
        self._filler_used = False

    def filler_for(self, tool_name: str) -> str:
        if tool_name in EXTRA_FILLERS:
            return EXTRA_FILLERS[tool_name]
        tool = self.registry.get(tool_name) if self.registry else None
        if tool is not None and tool.filler is not None:
            return tool.filler
        choices = [f for f in GENERIC_FILLERS if f != self._last_generic] or list(GENERIC_FILLERS)
        self._last_generic = self._rng.choice(choices)
        return self._last_generic

    def on_tool_call(self, tool_name: str, _args: dict | None = None) -> None:
        if self._filler_used:
            return
        self._filler_used = True
        phrase = self.filler_for(tool_name)
        if not phrase:
            return
        log.info("Заполнитель: %s", phrase)
        self._filler_thread = threading.Thread(target=self._play_filler, args=(phrase,), daemon=True)
        self._filler_thread.start()

    def wait_filler(self) -> None:
        if self._filler_thread is not None:
            self._filler_thread.join()
            self._filler_thread = None

    def _play_filler(self, phrase: str) -> None:
        try:
            with self._lock:
                self._speak_cached(phrase)
        except Exception as exc:  # noqa: BLE001
            log.warning("Заполнитель не прозвучал: %s", exc)

    def _speak_cached(self, text: str) -> None:
        if hasattr(self.speaker, "speak_cached"):
            self.speaker.speak_cached(text)
        else:
            self.speaker.speak(text)

    # ---------- прогрев кеша ----------

    def all_phrases(self) -> list[str]:
        phrases = list(GENERIC_FILLERS) + list(ACK_PHRASES) + list(EXTRA_FILLERS.values()) + list(GREETINGS.values())
        if self.registry:
            phrases += [t.filler for t in self.registry.all() if t.filler]
        return list(dict.fromkeys(phrases))

    def prefetch_async(self, extra: Iterable[str] = ()) -> None:
        if not hasattr(self.speaker, "prefetch"):
            return
        phrases = self.all_phrases() + list(extra)
        threading.Thread(target=self.speaker.prefetch, args=(phrases,), daemon=True).start()
