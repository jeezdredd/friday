import pytest

from friday.voice.listener import Endpointer, split_wake_command, strip_wake_word
from friday.voice.stt import clean_transcript
from friday.voice.tts import normalize_ru, split_sentences
from friday.voice.wakeword import contains_wake_word


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Пятница, включи свет.", "включи свет."),
        ("пятница включи свет", "включи свет"),
        ("Эй, Пятница! Какая погода?", "Какая погода?"),
        ("Пятницу позови", "позови"),
        ("Пятница.", ""),
        ("Включи свет", "Включи свет"),
        ("Какой сегодня день, пятница?", "Какой сегодня день, пятница?"),
    ],
)
def test_strip_wake_word(raw, expected):
    assert strip_wake_word(raw, "пятница") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Пятница, включи свет в комнате.", (True, "включи свет в комнате.")),
        ("Слушай, Пятница, какая завтра погода?", (True, "какая завтра погода?")),
        ("Пятница.", (True, "")),
        ("В пятницу пойдём в кино с друзьями.", (False, "")),
        ("Сегодня хорошая погода, давай погуляем.", (False, "")),
        ("Я думаю, что в эту пятница не подходит", (False, "")),
    ],
)
def test_split_wake_command(raw, expected):
    assert split_wake_command(raw, "пятница") == expected


def test_contains_wake_word():
    assert contains_wake_word("пятница", "пятница")
    assert contains_wake_word("[unk] пятница", "пятница")
    assert not contains_wake_word("[unk]", "пятница")


def _run(ep: Endpointer, levels):
    for i, level in enumerate(levels):
        if ep.feed(level):
            return i
    return None


def test_endpointer_stops_after_silence():
    ep = Endpointer(frame_seconds=0.1, noise_floor=0.005, silence_seconds=0.5, start_timeout=5)
    # 1 сек речи, потом тишина: должны остановиться через 0.5 сек тишины
    stop = _run(ep, [0.1] * 10 + [0.001] * 20)
    assert ep.speech_started and stop == 14


def test_endpointer_gives_up_without_speech():
    ep = Endpointer(frame_seconds=0.1, noise_floor=0.005, start_timeout=1.0)
    assert _run(ep, [0.001] * 30) == 9
    assert not ep.speech_started


def test_endpointer_ignores_chime():
    ep = Endpointer(frame_seconds=0.1, noise_floor=0.005, guard_seconds=0.25, start_timeout=1.0)
    _run(ep, [0.5, 0.5] + [0.001] * 10)
    assert not ep.speech_started


def test_endpointer_threshold_adapts_to_noise():
    ep = Endpointer(frame_seconds=0.1, noise_floor=0.05, start_timeout=1.0)
    _run(ep, [0.1] * 10)  # 0.1 < 3 * 0.05, это просто шумная комната
    assert not ep.speech_started


def test_whisper_hallucinations_filtered():
    assert clean_transcript("Продолжение следует...") == ""
    assert clean_transcript("Субтитры сделал DimaTorzok") == ""
    assert clean_transcript(" Включи свет ") == "Включи свет"


def test_normalize_numbers():
    out = normalize_ru("Сейчас 23°C, влажность 40%")
    assert "двадцать три градусов" in out
    assert "сорок процентов" in out
    assert not any(ch.isdigit() for ch in out)


def test_split_sentences():
    text = "Раз. " * 300
    chunks = split_sentences(text, max_len=100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")
