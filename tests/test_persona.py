import random

import pytest

from friday.prompts import BASE_PROMPT, render_base_prompt
from friday.voice.output import ACK_PHRASES, GREETINGS, VoiceOutput, part_of_day


def test_address_is_rendered_into_prompt():
    prompt = render_base_prompt("сэр")
    assert 'обращайся к пользователю "сэр"'.lower() in prompt.lower()
    assert "Без четверти девять, сэр." in prompt
    assert "{address}" not in prompt and "{address}" not in BASE_PROMPT


def test_prompt_mentions_all_three_inspirations_without_quotes():
    for name in ("Джарвис", "Пятница", "Эдит"):
        assert name in BASE_PROMPT
    assert "никогда не цитируешь фильмы" in BASE_PROMPT


@pytest.mark.parametrize(("hour", "part"), [(2, "night"), (7, "morning"), (13, "day"), (21, "evening")])
def test_part_of_day(hour, part):
    assert part_of_day(hour) == part
    assert GREETINGS[part]


class Recorder:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)


def test_ack_rotates_without_repeats():
    speaker = Recorder()
    voice = VoiceOutput(speaker, rng=random.Random(1))
    for _ in range(20):
        voice.ack()
    assert all(p in ACK_PHRASES for p in speaker.said)
    assert all(a != b for a, b in zip(speaker.said, speaker.said[1:], strict=False))


def test_greetings_are_prefetched():
    phrases = VoiceOutput(Recorder()).all_phrases()
    assert set(GREETINGS.values()) <= set(phrases)
    assert set(ACK_PHRASES) <= set(phrases)
