"""Детекторы wake word.

vosk (по умолчанию): офлайн, бесплатно, понимает русское "Пятница" без обучения.
    Распознаватель ограничен грамматикой из одного слова, поэтому работает быстро.
    Модель (~45 МБ) скачивается автоматически в ~/.friday/models при первом запуске.

porcupine: точнее и почти не даёт ложных срабатываний, но нужен бесплатный
    access key и обученное слово из Picovoice Console (см. README).
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np

from friday.config import settings
from friday.voice.audio import FRAME_SAMPLES, SAMPLE_RATE, to_int16_bytes

log = logging.getLogger(__name__)


class WakeWordDetector(Protocol):
    frame_samples: int

    def process(self, frame: np.ndarray) -> bool:
        """Скормить кадр аудио, вернуть True если услышали wake word."""

    def reset(self) -> None: ...


# ---------- Vosk ----------


def ensure_vosk_model(url: str = "", models_dir: Path | None = None) -> Path:
    url = url or settings.vosk_model_url
    models_dir = models_dir or settings.data_dir / "models"
    name = url.rsplit("/", 1)[-1].removesuffix(".zip")
    target = models_dir / name
    if target.exists():
        return target

    models_dir.mkdir(parents=True, exist_ok=True)
    archive = models_dir / f"{name}.zip"
    log.warning("Скачиваю модель для wake word: %s", url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        with archive.open("wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(models_dir)
    archive.unlink()
    return target


def contains_wake_word(text: str, wake_word: str) -> bool:
    return wake_word.lower() in text.lower().split()


class VoskWakeWord:
    """Распознаёт речь по полному словарю и ждёт точное слово.

    Грамматика из одного слова быстрее, но на практике "притягивает" к нему любую
    речь и даёт много ложных срабатываний, поэтому по умолчанию выключена.
    """

    frame_samples = FRAME_SAMPLES

    def __init__(self, wake_word: str = "", model_path: Path | None = None, grammar: bool = False):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.wake_word = (wake_word or settings.wake_word).lower()
        self._model = Model(str(model_path or ensure_vosk_model()))
        if grammar:
            spec = json.dumps([self.wake_word, "[unk]"], ensure_ascii=False)
            self._rec = KaldiRecognizer(self._model, SAMPLE_RATE, spec)
        else:
            self._rec = KaldiRecognizer(self._model, SAMPLE_RATE)

    def process(self, frame: np.ndarray) -> bool:
        data = to_int16_bytes(frame)
        if self._rec.AcceptWaveform(data):
            text = json.loads(self._rec.Result()).get("text", "")
        else:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
        if contains_wake_word(text, self.wake_word):
            self.reset()
            return True
        return False

    def reset(self) -> None:
        self._rec.Reset()


# ---------- Porcupine ----------


class PorcupineWakeWord:
    def __init__(self):
        import pvporcupine

        if not (settings.porcupine_access_key and settings.porcupine_keyword_path):
            raise RuntimeError("Для porcupine нужны PORCUPINE_ACCESS_KEY и PORCUPINE_KEYWORD_PATH в .env")
        kwargs = {
            "access_key": settings.porcupine_access_key,
            "keyword_paths": [settings.porcupine_keyword_path],
            "sensitivities": [settings.porcupine_sensitivity],
        }
        if settings.porcupine_model_path:  # для русского слова нужен porcupine_params_ru.pv
            kwargs["model_path"] = settings.porcupine_model_path
        self._p = pvporcupine.create(**kwargs)
        self.frame_samples = self._p.frame_length

    def process(self, frame: np.ndarray) -> bool:
        pcm = np.frombuffer(to_int16_bytes(frame), dtype=np.int16)
        return self._p.process(pcm) >= 0

    def reset(self) -> None:
        pass


def create_detector() -> WakeWordDetector:
    engine = settings.wake_engine.lower()
    if engine == "porcupine":
        return PorcupineWakeWord()
    if engine == "vosk":
        return VoskWakeWord()
    raise ValueError(f"Неизвестный WAKE_ENGINE: {settings.wake_engine}")
