"""Постоянный аудиовыход: поток открывается один раз, окончание речи по длительности звука."""

import sys
import types
from typing import ClassVar

import pytest

from friday.voice import player as player_mod


class FakeStream:
    instances: ClassVar[list["FakeStream"]] = []

    def __init__(self, samplerate, channels, dtype):
        self.samplerate = samplerate
        self.writes: list[bytes] = []
        self.started = self.closed = False
        self.latency = 0.5
        FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def write(self, data):
        self.writes.append(bytes(data))

    def stop(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_audio(monkeypatch):
    FakeStream.instances.clear()
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(RawOutputStream=FakeStream))
    sleeps: list[float] = []
    clock = {"t": 100.0}
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(player_mod.time, "sleep", sleeps.append)
    monkeypatch.setattr(player_mod.atexit, "register", lambda f: None)
    return sleeps, clock


def test_stream_opened_once_for_many_phrases(fake_audio):
    p = player_mod.PcmPlayer(16_000)
    p.play(b"\x00\x00" * 1600)
    p.play(b"\x00\x00" * 1600)
    assert len(FakeStream.instances) == 1
    assert FakeStream.instances[0].started


def test_waits_for_audio_duration_not_stream_close(fake_audio):
    sleeps, _ = fake_audio
    p = player_mod.PcmPlayer(16_000)
    duration = p.play(b"\x00\x00" * 16_000)  # одна секунда
    assert duration == pytest.approx(1.0)
    assert sleeps == [pytest.approx(1.0)]  # запись мгновенная, ждём остаток звука
    assert not FakeStream.instances[0].closed


def test_odd_chunks_are_not_split_mid_sample(fake_audio):
    p = player_mod.PcmPlayer(16_000)
    p.play_stream([b"\x01", b"\x02\x03", b"\x04\x05"])
    written = b"".join(FakeStream.instances[0].writes)
    assert written == b"\x01\x02\x03\x04"  # последний одиночный байт не дописан
    assert all(len(w) % 2 == 0 for w in FakeStream.instances[0].writes)


def test_empty_stream_returns_immediately(fake_audio):
    sleeps, _ = fake_audio
    assert player_mod.PcmPlayer(16_000).play_stream([]) == 0.0
    assert sleeps == []


def test_players_shared_per_samplerate():
    assert player_mod.get_player(22_050) is player_mod.get_player(22_050)
    assert player_mod.get_player(22_050) is not player_mod.get_player(48_000)
