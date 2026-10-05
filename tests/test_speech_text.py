import json

import pytest

from friday.voice.speech_text import (
    COMBINING_ACUTE,
    apply_pronunciations,
    load_pronunciations,
    normalize_punctuation,
    prepare_for_speech,
    render_stress,
)


@pytest.fixture(autouse=True)
def fresh_dictionary():
    load_pronunciations.cache_clear()
    yield
    load_pronunciations.cache_clear()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Свет включён", "Свет включён."),
        ("Готово — свет включён", "Готово, свет включён."),
        ("В комнате тепло (двадцать два градуса)", "В комнате тепло, двадцать два градуса."),
        ("Она сказала «привет»", "Она сказала привет."),
        ("Ты уверен??", "Ты уверен?"),
        ("Раз , два ,, три", "Раз, два, три."),
        ("Привет.Как дела", "Привет. Как дела."),
        ("Курс 2.5 и время 10:30", "Курс 2.5 и время 10:30."),
        ("**Важно**: свет включён", "Важно: свет включён."),
        ("- первое\n- второе", "первое. второе."),
        ("Подробнее тут https://example.com", "Подробнее тут."),
    ],
)
def test_normalize_punctuation(raw, expected):
    assert normalize_punctuation(raw) == expected


def test_pronunciations_whole_words_and_case():
    rules = {"Mac": "мак", "HomePod": "хоум под", "HomePod mini": "хоум под мини", "т.е.": "то есть"}
    assert apply_pronunciations("Включи HomePod mini на mac", rules) == "Включи хоум под мини на мак"
    assert apply_pronunciations("Macintosh", rules) == "Macintosh"  # не внутри слова
    assert apply_pronunciations("т.е. завтра", rules) == "то есть завтра"


def test_render_stress():
    assert render_stress("зам+ок", "plus") == "зам+ок"
    assert render_stress("зам+ок", "none") == "замок"
    assert render_stress("зам+ок", "acute") == "замо" + COMBINING_ACUTE + "к"


def test_prepare_for_speech_full_pipeline():
    out = prepare_for_speech("Включила HomePod — т.е. музыка играет", stress="none")
    assert out == "Включила хоум под, то есть музыка играет."


def test_user_dictionary_overrides_defaults(tmp_path):
    (tmp_path / "pronunciations.json").write_text(json.dumps({"Mac": "мэк", "Алматы": "Алмат+ы"}), encoding="utf-8")
    out = prepare_for_speech("Mac в Алматы", stress="plus")
    assert out == "мэк в Алмат+ы."


def test_elevenlabs_request(monkeypatch):
    from friday.config import settings
    from friday.voice.tts import ElevenLabs

    monkeypatch.setattr(settings, "elevenlabs_model", "eleven_multilingual_v2")
    monkeypatch.setattr(settings, "elevenlabs_stress", "acute")
    body = ElevenLabs.build_request("Включила HomePod — всё готово")
    assert body["text"] == "Включила хоум под, всё готово."
    assert body["voice_settings"]["stability"] == settings.elevenlabs_stability
    assert "language_code" not in body  # multilingual_v2 его не поддерживает

    monkeypatch.setattr(settings, "elevenlabs_model", "eleven_flash_v2_5")
    assert ElevenLabs.build_request("тест")["language_code"] == "ru"
