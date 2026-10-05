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

import hashlib
import logging
import re
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from friday.config import settings
from friday.voice.player import get_player
from friday.voice.player import warmup as warmup_player
from friday.voice.speech_text import prepare_for_speech

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
        text = prepare_for_speech(text, stress="none")
        if text:
            subprocess.run(["say", "-v", self.voice, "-r", str(self.rate), text], check=False)


class ElevenLabs:
    SAMPLE_RATE = 22_050  # pcm 22.05 кГц доступен на всех тарифах
    FALLBACK_MODEL = "eleven_multilingual_v2"
    NO_LANGUAGE_CODE = frozenset({"eleven_multilingual_v2"})

    def __init__(self, client: httpx.Client | None = None):
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY не задан в .env")
        if not settings.elevenlabs_voice_id:
            raise RuntimeError("ELEVENLABS_VOICE_ID не задан. Запусти: python -m friday.voice_setup")
        self._client = client or httpx.Client(
            base_url="https://api.elevenlabs.io/v1",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=30,
        )
        self.model = settings.elevenlabs_model
        self._send_language = self.model not in self.NO_LANGUAGE_CODE

    @classmethod
    def build_request(cls, text: str, model: str | None = None, language: bool | None = None) -> dict:
        model = model or settings.elevenlabs_model
        if language is None:
            language = model not in cls.NO_LANGUAGE_CODE
        body: dict = {
            "text": prepare_for_speech(text, stress=settings.elevenlabs_stress),
            "model_id": model,
            "voice_settings": {
                "stability": settings.elevenlabs_stability,
                "similarity_boost": settings.elevenlabs_similarity,
                "style": settings.elevenlabs_style,
                "speed": settings.elevenlabs_speed,
                "use_speaker_boost": settings.elevenlabs_speaker_boost,
            },
        }
        if language:
            body["language_code"] = settings.stt_language
        return body

    def _open(self, text: str, stream: bool) -> httpx.Response:
        """Отправляет запрос с самовосстановлением: если модель не принимает language_code,
        повторяем без него; если модель недоступна на тарифе, откатываемся на FALLBACK_MODEL."""
        suffix = "/stream" if stream else ""
        for _ in range(3):
            body = self.build_request(text, self.model, self._send_language)
            log.info("TTS [%s]: %s", self.model, body["text"])
            request = self._client.build_request(
                "POST",
                f"/text-to-speech/{settings.elevenlabs_voice_id}{suffix}",
                params={"output_format": f"pcm_{self.SAMPLE_RATE}"},
                json=body,
            )
            resp = self._client.send(request, stream=stream)
            if resp.status_code < 400:
                return resp

            resp.read()
            resp.close()
            error = resp.text.lower()
            if self._send_language and resp.status_code in (400, 422) and "language" in error:
                log.warning("Модель %s не принимает language_code, отправляю без него", self.model)
                self._send_language = False
                continue
            if self.model != self.FALLBACK_MODEL and resp.status_code in (400, 403, 404, 422) and "model" in error:
                log.warning(
                    "Модель %s недоступна (%s), переключаюсь на %s", self.model, resp.status_code, self.FALLBACK_MODEL
                )
                self.model = self.FALLBACK_MODEL
                self._send_language = False
                continue
            raise RuntimeError(f"ElevenLabs {resp.status_code}: {resp.text[:200]}")
        raise RuntimeError("ElevenLabs: не удалось синтезировать речь")

    def synthesize(self, text: str) -> bytes:
        resp = self._open(text, stream=False)
        return resp.content

    def speak(self, text: str) -> None:
        """Потоковое воспроизведение: звук начинает играть с первых байт ответа,
        а не после синтеза всей фразы. Поток вывода общий и постоянно открыт."""
        if not text:
            return
        started = time.monotonic()
        resp = self._open(text, stream=True)
        timings: dict[str, float] = {}

        def chunks():
            for chunk in resp.iter_bytes():
                if "first" not in timings:
                    timings["first"] = time.monotonic() - started
                    log.info("TTS первый звук через %.2f сек", timings["first"])
                yield chunk

        try:
            duration = get_player(self.SAMPLE_RATE).play_stream(chunks())
        finally:
            resp.close()
        log.info("TTS %.2f сек звука, всего %.2f сек", duration, time.monotonic() - started)

    def warmup(self) -> None:
        warmup_player(self.SAMPLE_RATE)

    # ---------- кеш коротких фраз (заполнители, "Да?") ----------

    def _cache_path(self, text: str) -> Path:
        s = settings
        key = "|".join(
            map(
                str,
                (
                    s.elevenlabs_voice_id,
                    self.model,
                    s.elevenlabs_stability,
                    s.elevenlabs_similarity,
                    s.elevenlabs_style,
                    s.elevenlabs_speed,
                    s.elevenlabs_stress,
                    text,
                ),
            )
        )
        return s.data_dir / "tts_cache" / f"{hashlib.sha1(key.encode()).hexdigest()}.pcm"

    def cached_audio(self, text: str) -> bytes:
        path = self._cache_path(text)
        if path.exists():
            return path.read_bytes()
        audio = self.synthesize(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio

    def prefetch(self, phrases: list[str]) -> None:
        """Синтезирует фразы заранее, чтобы потом они звучали мгновенно. Тратит лимит один раз."""
        for phrase in phrases:
            try:
                self.cached_audio(phrase)
            except Exception as exc:  # noqa: BLE001
                log.warning("Не удалось закешировать %r: %s", phrase, exc)
                return

    def speak_cached(self, text: str) -> None:
        get_player(self.SAMPLE_RATE).play(self.cached_audio(text))


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
        text = normalize_ru(prepare_for_speech(text, stress="plus"))
        player = get_player(self.SAMPLE_RATE)
        for chunk in split_sentences(text, self.MAX_CHARS):
            # put_accent / put_yo: silero сам расставит ударения и ё там, где их нет в тексте
            audio = self._model.apply_tts(
                text=chunk, speaker=self.speaker, sample_rate=self.SAMPLE_RATE, put_accent=True, put_yo=True
            )
            pcm = (audio.clamp(-1, 1) * 32767).short().numpy().tobytes()
            player.play(pcm)

    def warmup(self) -> None:
        warmup_player(self.SAMPLE_RATE)


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
