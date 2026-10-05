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


def transcribe(audio: np.ndarray) -> str:
    if audio.size < 1600:  # меньше 0.1 сек, это не речь
        return ""
    segments, _ = _model().transcribe(audio, language=settings.stt_language, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()
