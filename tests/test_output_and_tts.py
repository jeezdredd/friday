import json

import httpx
import pytest

from friday.config import settings
from friday.voice.audio import AIRPLAY_LATENCY, LOCAL_LATENCY, output_latency
from friday.voice.listener import is_self_echo
from friday.voice.tts import ElevenLabs


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("HomePod mini", AIRPLAY_LATENCY),
        ("Living Room AirPlay", AIRPLAY_LATENCY),
        ("MacBook Pro Speakers", LOCAL_LATENCY),
        ("", LOCAL_LATENCY),
    ],
)
def test_output_latency_autodetect(device, expected):
    assert output_latency(device) == expected


def test_output_latency_override():
    assert output_latency("HomePod", override="3.5") == 3.5


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("в комнате двадцать один градус", True),  # хвост ответа
        ("В комнате двадцать один градус, на улице солнечно.", True),
        ("в комнате двадцать один градус на улице", True),
        ("а завтра будет дождь?", False),
        ("включи свет", False),
    ],
)
def test_self_echo(heard, expected):
    answer = "В комнате двадцать один градус, на улице солнечно."
    assert is_self_echo(heard, answer) is expected


@pytest.fixture
def elevenlabs_settings(monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "voice")
    monkeypatch.setattr(settings, "elevenlabs_model", "eleven_v4_turbo")


def _client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.elevenlabs.io/v1", transport=httpx.MockTransport(handler))


def test_falls_back_when_model_unavailable(elevenlabs_settings):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["model_id"], "language_code" in body))
        if body["model_id"] == "eleven_v4_turbo":
            return httpx.Response(403, json={"detail": {"message": "This model is not available on your plan"}})
        return httpx.Response(200, content=b"\x00\x00")

    tts = ElevenLabs(client=_client(handler))
    assert tts.synthesize("привет") == b"\x00\x00"
    assert seen == [("eleven_v4_turbo", True), ("eleven_multilingual_v2", False)]
    assert tts.model == "eleven_multilingual_v2"  # дальше сразу на рабочей модели


def test_retries_without_language_code(elevenlabs_settings):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append("language_code" in body)
        if "language_code" in body:
            return httpx.Response(400, json={"detail": {"message": "language_code is not supported for this model"}})
        return httpx.Response(200, content=b"ok")

    tts = ElevenLabs(client=_client(handler))
    assert tts.synthesize("привет") == b"ok"
    assert seen == [True, False]
    assert tts.model == "eleven_v4_turbo"


def test_auth_error_is_not_swallowed(elevenlabs_settings):
    tts = ElevenLabs(client=_client(lambda r: httpx.Response(401, json={"detail": {"status": "invalid_api_key"}})))
    with pytest.raises(RuntimeError, match="401"):
        tts.synthesize("привет")
