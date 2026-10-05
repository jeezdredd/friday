"""Синтез речи.

Движок выбирается через TTS_ENGINE:
    say          системный голос macOS, работает сразу
    silero       локально и бесплатно, хорошие русские голоса (нужен torch)
    elevenlabs   лучшее качество, голос Пятницы создаётся командой
                 python -m friday.voice_setup

Чтобы звук шёл в HomePod, выбери его устройством вывода на маке.
Свой движок: класс с методом speak(text), добавь его в create_speaker().
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Protocol

import httpx

from friday.config import settings

log = logging.getLogger(__name__)


class Speaker(Protocol):
    def speak(self, text: str) -> None: ...


class PrintOnly:
    def speak(self, text: str) -> None:
        pass


class MacSay:
    def __init__(self, voice: str = "", rate: int = 0):
        self.voice = voice or settings.tts_voice
        self.rate = rate or settings.tts_rate

    def speak(self, text: str) -> None:
        if text:
            subprocess.run(["say", "-v", self.voice, "-r", str(self.rate), text], check=False)


class ElevenLabs:
    SAMPLE_RATE = 22_050  # pcm 22.05 кГц доступен на всех тарифах

    def __init__(self):
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY не задан в .env")
        if not settings.elevenlabs_voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID не задан. Запусти: python -m friday.voice_setup")
        self._client = httpx.Client(
            base_url="https://api.elevenlabs.io/v1",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=30,
        )

    def synthesize(self, text: str) -> bytes:
        body = {"text": text, "model_id": settings.elevenlabs_model}
        if "v2_5" in settings.elevenlabs_model:  # явный язык поддерживают только flash/turbo v2.5
            body["language_code"] = settings.stt_language
        resp = self._client.post(
            f"/text-to-speech/{settings.elevenlabs_voice_id}",
            params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"ElevenLabs {resp.status_code}: {resp.text[:200]}")
        return resp.content

    def speak(self, text: str) -> None:
        if not text:
            return
        import numpy as np
        import sounddevice as sd

        audio = np.frombuffer(self.synthesize(text), dtype=np.int16)
        sd.play(audio, self.SAMPLE_RATE)
        sd.wait()


class Silero:
    SAMPLE_RATE = 48_000
    MAX_CHARS = 800  # у silero ограничение на длину одного куска

    def __init__(self, speaker: str = ""):
        import torch

        self.speaker = speaker or settings.silero_speaker
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models", model="silero_tts", language="ru", speaker="v4_ru"
        )

    def speak(self, text: str) -> None:
        import sounddevice as sd

        for chunk in split_sentences(normalize_ru(text), self.MAX_CHARS):
            audio = self._model.apply_tts(text=chunk, speaker=self.speaker, sample_rate=self.SAMPLE_RATE)
            sd.play(audio.numpy(), self.SAMPLE_RATE)
            sd.wait()


# ---------- текст для локальных движков ----------

_UNITS = {"%": " процентов", "°C": " градусов", "°": " градусов", "км/ч": " километров в час"}
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def normalize_ru(text: str) -> str:
    """Silero не читает цифры, переводим их в слова."""
    from num2words import num2words

    for unit, word in _UNITS.items():
        text = text.replace(unit, word)

    def repl(m: re.Match) -> str:
        raw = m.group().replace(",", ".")
        value = float(raw) if "." in raw else int(raw)
        return num2words(value, lang="ru")

    return _NUMBER.sub(repl, text)


def split_sentences(text: str, max_len: int) -> list[str]:
    """Режет текст на куски не длиннее max_len по границам предложений.
    Слишком длинное предложение режется по пробелам, в крайнем случае по символам."""
    pieces: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        while len(s) > max_len:
            cut = s.rfind(" ", 0, max_len + 1)
            cut = cut if cut > 0 else max_len
            pieces.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            pieces.append(s)

    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > max_len:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


@lru_cache(maxsize=1)
def create_speaker() -> Speaker:
    engine = settings.tts_engine.lower()
    try:
        if engine == "elevenlabs":
            return ElevenLabs()
        if engine == "silero":
            return Silero()
    except Exception as exc:  # noqa: BLE001
        log.warning("TTS %s недоступен (%s), откатываюсь на системный голос", engine, exc)
    return MacSay() if shutil.which("say") else PrintOnly()


# обратная совместимость
default_speaker = create_speaker
