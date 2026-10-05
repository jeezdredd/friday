"""Общий поток с микрофона: 16 кГц моно float32, кадры фиксированного размера."""

from __future__ import annotations

import queue
from typing import Self

import numpy as np

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512  # 32 мс, совпадает с размером кадра Porcupine


class MicStream:
    def __init__(self, sample_rate: int = SAMPLE_RATE, frame_samples: int = FRAME_SAMPLES):
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None

    def __enter__(self) -> Self:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.frame_samples,
            callback=self._callback,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()

    def _callback(self, indata, frames, time, status):
        self._q.put(indata[:, 0].copy())

    def read(self, timeout: float | None = None) -> np.ndarray:
        return self._q.get(timeout=timeout)

    def flush(self) -> None:
        """Выкинуть накопленное, например то, что микрофон слышал, пока говорила сама Пятница."""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return


def to_int16_bytes(frame: np.ndarray) -> bytes:
    return (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
