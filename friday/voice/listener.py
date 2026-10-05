"""Слушаем wake word, затем записываем фразу до паузы."""

from __future__ import annotations

import difflib
import logging
import re
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from friday.config import settings
from friday.voice.audio import SAMPLE_RATE, MicStream, output_latency, rms
from friday.voice.wakeword import WakeWordDetector

log = logging.getLogger(__name__)

PREROLL_SECONDS = 2.0
CHIME_SOUND = "/System/Library/Sounds/Tink.aiff"


@dataclass
class NoiseFloor:
    """Скользящая оценка фонового шума, чтобы порог речи подстраивался под комнату."""

    level: float = 0.005
    alpha: float = 0.05

    def update(self, value: float) -> None:
        # громкие всплески (речь) почти не тянут оценку вверх
        value = min(value, self.level * 3)
        self.level = (1 - self.alpha) * self.level + self.alpha * value

    def threshold(self, min_threshold: float = 0.01, factor: float = 3.0) -> float:
        return max(min_threshold, self.level * factor)


_EPS = 1e-6


@dataclass
class Endpointer:
    """Решает, когда фраза началась и закончилась. Получает громкость кадра (RMS),
    без I/O, поэтому легко тестируется.

    feed() возвращает True, когда пора остановиться: либо фраза закончилась паузой,
    либо речь так и не началась за start_timeout (тогда speech_started == False).
    """

    frame_seconds: float
    noise_floor: float = 0.005
    silence_seconds: float = 0.9
    max_seconds: float = 15.0
    start_timeout: float = 5.0
    guard_seconds: float = 0.0  # игнор начала, например звук сигнала
    min_threshold: float = 0.01
    noise_factor: float = 3.0

    speech_started: bool = False
    _frames: int = 0
    _silent_frames: int = 0

    @property
    def threshold(self) -> float:
        return max(self.min_threshold, self.noise_floor * self.noise_factor)

    @property
    def elapsed(self) -> float:
        return self._frames * self.frame_seconds

    def feed(self, level: float) -> bool:
        self._frames += 1
        loud = self.elapsed > self.guard_seconds + _EPS and level >= self.threshold

        if not self.speech_started:
            if loud:
                self.speech_started = True
                return False
            return self.elapsed >= self.start_timeout - _EPS

        self._silent_frames = 0 if loud else self._silent_frames + 1
        silence = self._silent_frames * self.frame_seconds
        return silence >= self.silence_seconds - _EPS or self.elapsed >= self.max_seconds - _EPS


class Listener:
    def __init__(self, mic: MicStream, detector: WakeWordDetector, latency: float | None = None):
        self.mic = mic
        self.detector = detector
        self.latency = output_latency(override=settings.output_latency) if latency is None else latency
        log.info("Задержка вывода звука: %.1f сек", self.latency)
        self.noise = NoiseFloor()
        self.frame_seconds = mic.frame_samples / SAMPLE_RATE
        self._ring: deque[np.ndarray] = deque(maxlen=max(1, int(PREROLL_SECONDS / self.frame_seconds)))
        self._preroll = np.zeros(0, dtype=np.float32)

    def wait_for_wake_word(self) -> None:
        """Блокирует до wake word. Запоминает последние ~1.5 сек аудио, чтобы не потерять
        начало команды, сказанной на одном дыхании: "Пятница, включи свет"."""
        self._ring.clear()
        self.detector.reset()
        while True:
            frame = self.mic.read()
            self._ring.append(frame)
            self.noise.update(rms(frame))
            if self.detector.process(frame):
                self._preroll = np.concatenate(self._ring)
                return

    def record_phrase(self, with_preroll: bool = True, start_timeout: float | None = None) -> np.ndarray:
        """Пишет фразу до паузы. Если речь так и не началась, возвращает пустой массив."""
        ep = Endpointer(
            frame_seconds=self.frame_seconds,
            noise_floor=self.noise.level,
            silence_seconds=settings.silence_seconds,
            max_seconds=settings.max_phrase_seconds,
            start_timeout=start_timeout or settings.start_timeout_seconds,
            guard_seconds=0.3 if settings.chime else 0.0,
        )
        frames: list[np.ndarray] = []
        while True:
            frame = self.mic.read()
            frames.append(frame)
            if ep.feed(rms(frame)):
                break

        preroll, self._preroll = self._preroll, np.zeros(0, dtype=np.float32)
        parts = [preroll] if with_preroll and preroll.size else []
        if ep.speech_started:
            parts += frames
        # Сказали только "Пятница" и замолчали: отдаём пре-ролл, чтобы Whisper увидел обращение
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    def after_speaking(self) -> None:
        """Пока Пятница говорила, микрофон слышал её саму. Ждём, пока колонка доиграет
        хвост (у AirPlay это пара секунд), и выбрасываем всё услышанное."""
        time.sleep(self.latency)
        self.reset()

    def reset(self) -> None:
        self.mic.flush()
        self.detector.reset()

    def chime(self) -> None:
        # Через AirPlay сигнал придёт с опозданием и наложится на речь, тогда он только мешает
        if self.latency < 0.5:
            chime()


def chime() -> None:
    if settings.chime and shutil.which("afplay"):
        subprocess.Popen(["afplay", "-v", "0.4", CHIME_SOUND])


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower().replace("ё", "е"))


def is_self_echo(heard: str, last_answer: str, threshold: float = 0.6) -> bool:
    """Микрофон расслышал хвост ответа самой Пятницы, а не пользователя."""
    heard_w, answer_w = _words(heard), _words(last_answer)
    if not heard_w or not answer_w:
        return False
    if " ".join(heard_w) in " ".join(answer_w):
        return True
    return difflib.SequenceMatcher(None, heard_w, answer_w).ratio() >= threshold


def split_wake_command(text: str, wake_word: str = "", max_position: int = 3) -> tuple[bool, str]:
    """Второй уровень проверки после детектора: было ли это обращение к ассистенту.

    Ищет слово-обращение среди первых max_position слов расшифровки Whisper.
    Возвращает (обращались ли, команда после обращения).
        "Пятница, включи свет"          -> (True, "включи свет")
        "Слушай, Пятница, какая погода" -> (True, "какая погода")
        "В пятницу пойдём в кино"       -> (False, "")
    """
    wake = (wake_word or settings.wake_word).lower()
    words = list(re.finditer(r"\w+", text))
    for m in words[:max_position]:
        if m.group().lower() == wake:
            rest = text[m.end() :]
            return True, re.sub(r"^\W+", "", rest).strip()
    return False, ""


def strip_wake_word(text: str, wake_word: str = "") -> str:
    """Убирает обращение из начала фразы: "Пятница, включи свет" -> "включи свет"."""
    wake = (wake_word or settings.wake_word).lower()
    stem = re.escape(wake[:-1] if len(wake) > 4 else wake)  # пятница / пятницу / пятниц
    text = re.sub(rf"^\W*(?:эй\W+|хей\W+)?{stem}\w*\W*", "", text.strip(), flags=re.IGNORECASE)
    return text.strip()
