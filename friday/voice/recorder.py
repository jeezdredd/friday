"""Запись с микрофона по принципу push-to-talk: Enter начать, Enter закончить."""

from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16_000  # whisper ожидает 16 кГц моно


def record_push_to_talk(prompt: str = "Enter: говорить") -> np.ndarray:
    import sounddevice as sd  # импорт здесь, чтобы текстовый режим работал без PortAudio

    input(prompt)
    chunks: list[np.ndarray] = []
    stop = threading.Event()

    def callback(indata, frames, time, status):
        chunks.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
        threading.Thread(target=lambda: (input("Слушаю... Enter: стоп"), stop.set()), daemon=True).start()
        stop.wait()

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).flatten()
