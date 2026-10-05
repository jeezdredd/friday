import itertools
import json
import random
import threading
import time

import httpx
import pytest

from friday.config import settings
from friday.tools import ToolRegistry
from friday.voice.output import GENERIC_FILLERS, VoiceOutput
from friday.voice.tts import ElevenLabs


class RecordingSpeaker:
    def __init__(self, delay: float = 0.0):
        self.said: list[str] = []
        self.delay = delay
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        time.sleep(self.delay)
        with self._lock:
            self.said.append(text)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()

    def get_weather() -> str:
        """Погода."""
        return "ok"

    def set_light() -> str:
        """Свет."""
        return "ok"

    def other() -> str:
        """Что-то."""
        return "ok"

    reg.register(get_weather, filler="Смотрю прогноз.")
    reg.register(set_light, filler="")
    reg.register(other)
    return reg


def test_filler_once_per_request_and_before_answer():
    speaker = RecordingSpeaker(delay=0.05)
    voice = VoiceOutput(speaker, _registry())
    voice.begin_request()
    voice.on_tool_call("get_weather")
    voice.on_tool_call("other")  # второй раунд инструментов не добавляет ещё одну фразу
    voice.speak("Тепло, солнечно.")
    assert speaker.said == ["Смотрю прогноз.", "Тепло, солнечно."]


def test_silent_tool_has_no_filler():
    speaker = RecordingSpeaker()
    voice = VoiceOutput(speaker, _registry())
    voice.begin_request()
    voice.on_tool_call("set_light")
    voice.speak("Включила.")
    assert speaker.said == ["Включила."]


def test_generic_filler_does_not_repeat_twice_in_a_row():
    voice = VoiceOutput(RecordingSpeaker(), _registry(), rng=random.Random(0))
    picks = [voice.filler_for("other") for _ in range(30)]
    assert all(p in GENERIC_FILLERS for p in picks)
    assert all(a != b for a, b in itertools.pairwise(picks))


def test_all_phrases_include_tool_fillers():
    phrases = VoiceOutput(RecordingSpeaker(), _registry()).all_phrases()
    assert "Смотрю прогноз." in phrases and "Да?" in phrases and "" not in phrases


# ---------- ElevenLabs: кеш и поток ----------


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice")
    monkeypatch.setattr(settings, "elevenlabs_model", "eleven_v4_turbo")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)["text"]))
        return httpx.Response(200, content=b"\x01\x00" * 100)

    client = httpx.Client(base_url="https://api.elevenlabs.io/v1", transport=httpx.MockTransport(handler))
    return ElevenLabs(client=client), calls


def test_cached_audio_hits_api_once(eleven):
    tts, calls = eleven
    assert tts.cached_audio("Секунду.") == tts.cached_audio("Секунду.")
    assert len(calls) == 1
    assert (settings.data_dir / "tts_cache").exists()


def test_cache_key_depends_on_voice_settings(eleven, monkeypatch):
    tts, calls = eleven
    tts.cached_audio("Секунду.")
    monkeypatch.setattr(settings, "elevenlabs_speed", 1.1)
    tts.cached_audio("Секунду.")
    assert len(calls) == 2


def test_streaming_uses_stream_endpoint(eleven):
    tts, calls = eleven
    resp = tts._open("Привет.", stream=True)
    assert b"".join(resp.iter_bytes()) == b"\x01\x00" * 100
    assert calls[-1][0].endswith("/text-to-speech/voice/stream")


# ---------- кеширование промпта ----------


def test_system_prompt_cache_breakpoint_before_dynamic_context():
    from friday.agent import build_system_blocks
    from friday.prompts import BASE_PROMPT

    static, dynamic = build_system_blocks()
    assert static["text"] == BASE_PROMPT and static["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in dynamic and "Сейчас:" in dynamic["text"]
