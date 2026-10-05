"""Голосовая проверка доступа при запуске.

Пятница просит сказать кодовое слово ("подтверждаю"). Доступ открывается, только если
совпали и слово (Whisper), и голос (отпечаток владельца). Несколько попыток, затем
"Доступ запрещён" и выход.

Это удобство и защита от случайного запуска чужим человеком, а не настоящая
аутентификация: запись голоса владельца может её пройти.
"""

from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from friday.voice.speaker_id import SpeakerID

log = logging.getLogger(__name__)

MIN_AUDIO_SECONDS = 0.4


@dataclass(frozen=True)
class AuthResult:
    granted: bool
    attempts: int
    score: float | None = None
    heard: str = ""


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower().replace("ё", "е"))


def phrase_matches(heard: str, phrase: str) -> bool:
    """Кодовое слово с поправкой на распознавание: "подтверждаю", "Подтверждаю!",
    "подтверждаю это я", "потверждаю" засчитываются; "не подтверждаю" нет."""
    target = phrase.lower().replace("ё", "е")
    words = _words(heard)
    if "не" in words:
        return False
    stem = target[: max(4, len(target) - 2)]
    for w in words:
        if w.startswith(stem) or difflib.SequenceMatcher(None, w, target).ratio() >= 0.8:
            return True
    return False


class Messages:
    def __init__(self, phrase: str):
        self.prompt = f"Требуется голосовая идентификация. Скажи: {phrase}."
        self.not_heard = f"Не расслышала. Скажи: {phrase}."
        self.wrong_phrase = f"Нужно сказать: {phrase}."
        self.retry = "Голос не распознан. Повтори."
        self.denied = "Голос не распознан. Доступ запрещён."

    @staticmethod
    def granted(name: str) -> str:
        return f"Личность подтверждена. Приветствую, {name}. Чем могу помочь?"

    def all(self, name: str) -> list[str]:
        return [self.prompt, self.not_heard, self.wrong_phrase, self.retry, self.denied, self.granted(name)]


def authenticate(
    record: Callable[[], np.ndarray],
    transcribe: Callable[[np.ndarray], str],
    speaker_id: SpeakerID,
    say: Callable[[str], None],
    phrase: str = "подтверждаю",
    attempts: int = 3,
) -> AuthResult:
    msg = Messages(phrase)
    say(msg.prompt)
    best: float | None = None
    heard = ""
    for attempt in range(1, attempts + 1):
        audio = record()
        last = attempt == attempts
        if audio.size < MIN_AUDIO_SECONDS * 16_000:
            log.info("Проверка доступа %d: тишина", attempt)
            if not last:
                say(msg.not_heard)
            continue

        heard = transcribe(audio)
        verification = speaker_id.verify(audio)
        best = verification.score if best is None else max(best, verification.score)
        phrase_ok = phrase_matches(heard, phrase)
        voice_ok = verification.is_owner
        log.info(
            "Проверка доступа %d: услышала %r, слово %s, голос %.2f (порог %.2f) %s",
            attempt,
            heard,
            "да" if phrase_ok else "нет",
            verification.score,
            verification.threshold,
            "да" if voice_ok else "нет",
        )
        if phrase_ok and voice_ok:
            say(msg.granted(speaker_id.voiceprint.name))
            return AuthResult(True, attempt, verification.score, heard)
        if not last:
            # если слово верное, а голос нет, честно говорим про голос; иначе подсказываем слово
            say(msg.retry if phrase_ok else msg.wrong_phrase)

    say(msg.denied)
    return AuthResult(False, attempts, best, heard)
