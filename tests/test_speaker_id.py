"""Голосовая идентификация без настоящей модели: отпечатки подменены детерминированными векторами."""

import numpy as np
import pytest

from friday.config import settings
from friday.enroll import find_outliers
from friday.voice import speaker_id as sid


def vec(seed: int, noise: float = 0.0, base_seed: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.random.default_rng(base_seed if base_seed is not None else seed).normal(size=256)
    return sid.normalize(base + rng.normal(size=256) * noise)


class FakeEmbedder:
    """Отпечаток "голоса" зашит в первый сэмпл аудио: 1 = владелец, 2 = гость."""

    def __init__(self):
        self.voices = {1: vec(1), 2: vec(2)}

    def embed(self, audio):
        return self.voices[int(audio[0])]


def owner_vp(threshold=0.5):
    return sid.Voiceprint(name="Тест", embedding=list(vec(1)), threshold=threshold, samples=5)


def audio(voice: int, seconds: float = 2.0) -> np.ndarray:
    a = np.zeros(int(16_000 * seconds), dtype=np.float32)
    a[0] = voice
    return a


def test_calibration_tracks_consistency():
    tight = [vec(10 + i, noise=0.2, base_seed=1) for i in range(5)]
    loose = [vec(20 + i, noise=1.2, base_seed=1) for i in range(5)]
    t_tight, scores_tight = sid.calibrate_threshold(tight)
    t_loose, _ = sid.calibrate_threshold(loose)
    assert t_tight == sid.THRESHOLD_CEIL  # очень стабильный голос упирается в потолок
    assert sid.THRESHOLD_FLOOR <= t_loose < t_tight
    assert len(scores_tight) == 5


def test_outlier_phrase_is_detected():
    samples = [vec(30 + i, noise=0.3, base_seed=1) for i in range(4)] + [vec(99)]
    assert find_outliers(samples) == [4]


def test_voiceprint_roundtrip_is_private(tmp_path):
    path = sid.save_voiceprint(owner_vp(), tmp_path / "vp.json")
    assert (path.stat().st_mode & 0o777) == 0o600
    loaded = sid.load_voiceprint(path)
    assert loaded.name == "Тест" and np.allclose(loaded.vector, vec(1))


def test_threshold_override(monkeypatch):
    monkeypatch.setattr(settings, "voice_id_threshold", 0.99)
    v = sid.SpeakerID(owner_vp(0.5), FakeEmbedder()).verify(audio(1))
    assert v.threshold == 0.99


def test_gate_owner_stranger_and_short():
    gate = sid.IdentityGate(sid.SpeakerID(owner_vp(), FakeEmbedder()))
    owner, guest, short = gate.identify(audio(1)), gate.identify(audio(2)), gate.identify(audio(2, 0.5))
    assert owner.known and not owner.stranger and owner.name == "Тест"
    assert guest.stranger and not guest.known
    assert not short.known and not short.stranger  # слишком коротко, чтобы судить
    assert "Тест" in gate.context_note(owner)
    assert "гость" in gate.context_note(guest)
    assert gate.context_note(short) is None


def test_owner_only_policy():
    greet = sid.IdentityGate(sid.SpeakerID(owner_vp(), FakeEmbedder()), policy="greet")
    strict = sid.IdentityGate(sid.SpeakerID(owner_vp(), FakeEmbedder()), policy="owner_only")
    guest, short = strict.identify(audio(2)), strict.identify(audio(2, 0.5))
    assert greet.allowed(guest)
    assert not strict.allowed(guest)
    assert strict.allowed(short)  # "Пятница" без команды не отклоняем по короткой фразе


def test_greets_once_per_session_and_after_idle():
    gate = sid.IdentityGate(sid.SpeakerID(owner_vp(), FakeEmbedder()), greet_after_minutes=30)
    owner, guest = gate.identify(audio(1)), gate.identify(audio(2))
    assert gate.should_greet(owner, now=0)
    assert not gate.should_greet(owner, now=60)
    assert not gate.should_greet(guest, now=10_000)
    assert gate.should_greet(owner, now=60 + 30 * 60)


def test_disabled_gate_is_transparent():
    gate = sid.IdentityGate(None)
    identity = gate.identify(audio(1))
    assert not gate.enabled and identity.verification is None
    assert gate.allowed(identity) and not gate.should_greet(identity)
    assert gate.context_note(identity) is None


def test_invalid_policy():
    with pytest.raises(ValueError):
        sid.IdentityGate(None, policy="paranoid")


def test_agent_context_includes_speaker_and_owner_name(monkeypatch):
    from friday.agent import build_context

    monkeypatch.setattr(settings, "user_name", "")
    sid.save_voiceprint(owner_vp())
    ctx = build_context(speaker_note="Сейчас говорит Тест, владелец, голос подтверждён.")
    assert "- Владелец: Тест" in ctx
    assert "- Голос: Сейчас говорит Тест" in ctx
