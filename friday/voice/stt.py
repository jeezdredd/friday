"""Распознавание речи через faster-whisper (локально, без облака)."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from friday.config import settings


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    # int8 на CPU быстро работает и на Apple Silicon, и на Intel
    return WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")


def warmup() -> None:
    """Загрузить модель заранее, чтобы первый ответ не тормозил."""
    _model()


# Whisper на тишине и шуме любит выдумывать титры
_HALLUCINATIONS = (
    "продолжение следует",
    "субтитры",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "редактор субтитров",
)


def clean_transcript(text: str) -> str:
    """Обрезает пробелы и выкидывает типичные галлюцинации Whisper."""
    text = text.strip()
    low = text.lower()
    return "" if any(h in low for h in _HALLUCINATIONS) else text


DEFAULT_HINT = "Пятница, включи свет. Какая погода?"


def transcribe(audio: np.ndarray | None, hint: str | None = None) -> str:
    """hint: ожидаемые слова. Whisper смещается к ним, это сильно помогает на коротких
    фразах без контекста, например на кодовом слове при проверке доступа."""
    if audio is None or audio.size < 1600:  # меньше 0.1 сек, это не речь
        return ""
    segments, _ = _model().transcribe(
        audio,
        language=settings.stt_language,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
        initial_prompt=hint or DEFAULT_HINT,
    )
    return clean_transcript(" ".join(s.text.strip() for s in segments))
