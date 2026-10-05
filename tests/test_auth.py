import numpy as np
import pytest

from friday.voice.auth import Messages, authenticate, phrase_matches
from friday.voice.speaker_id import SpeakerID, Voiceprint, normalize


@pytest.mark.parametrize(
    ("heard", "ok"),
    [
        ("Подтверждаю.", True),
        ("подтверждаю, это я", True),
        ("Потверждаю", True),  # ошибка распознавания
        ("ПОДТВЕРЖДАЮ!", True),
        ("не подтверждаю", False),
        ("привет", False),
        ("", False),
    ],
)
def test_phrase_matches(heard, ok):
    assert phrase_matches(heard, "подтверждаю") is ok


class FakeEmbedder:
    def __init__(self):
        rng = np.random.default_rng(0)
        self.voices = {1: normalize(rng.normal(size=256)), 2: normalize(rng.normal(size=256))}

    def embed(self, audio):
        return self.voices[int(audio[0])]


def owner():
    emb = FakeEmbedder()
    vp = Voiceprint(name="Тест", embedding=list(emb.voices[1]), threshold=0.5)
    return SpeakerID(vp, emb)


def clip(voice: int, text: str) -> tuple[np.ndarray, str]:
    a = np.zeros(16_000, dtype=np.float32)
    a[0] = voice
    return a, text


def run(clips, attempts=3):
    queue = list(clips)
    texts = {}
    said = []

    def record():
        audio, text = queue.pop(0)
        texts[id(audio)] = text
        return audio

    result = authenticate(record, lambda a: texts[id(a)], owner(), said.append, attempts=attempts)
    return result, said


def test_granted_on_first_try():
    result, said = run([clip(1, "Подтверждаю.")])
    assert result.granted and result.attempts == 1
    assert said == [Messages("подтверждаю").prompt, Messages.granted("Тест")]


def test_stranger_is_denied_after_all_attempts():
    result, said = run([clip(2, "Подтверждаю.")] * 3)
    m = Messages("подтверждаю")
    assert not result.granted and result.attempts == 3
    assert said == [m.prompt, m.retry, m.retry, m.denied]


def test_owner_with_wrong_word_gets_hint_then_passes():
    result, said = run([clip(1, "привет"), clip(1, "подтверждаю")])
    m = Messages("подтверждаю")
    assert result.granted and result.attempts == 2
    assert said == [m.prompt, m.wrong_phrase, Messages.granted("Тест")]


def test_silence_counts_as_attempt():
    silence = (np.zeros(100, dtype=np.float32), "")
    result, said = run([silence, silence, silence])
    m = Messages("подтверждаю")
    assert not result.granted
    assert said == [m.prompt, m.not_heard, m.not_heard, m.denied]
