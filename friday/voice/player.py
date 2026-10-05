"""Постоянный аудиовыход.

Открывать поток на каждую фразу дорого, особенно для AirPlay (HomePod): каждое
открытие заново поднимает сессию с колонкой, а закрытие ждёт, пока выйдет весь
сетевой буфер. На практике это 4-6 лишних секунд на каждом ответе.

Поэтому поток открывается один раз и живёт до выхода. Пока писать нечего,
звуковая карта сама проигрывает тишину. Окончание речи считается по длительности
записанного звука, а не по закрытию потока.

Ограничение: устройство вывода фиксируется при первом воспроизведении. Если
переключил вывод (например, на HomePod), перезапусти Пятницу.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from collections.abc import Iterable

log = logging.getLogger(__name__)

SAMPLE_WIDTH = 2  # int16


class PcmPlayer:
    def __init__(self, samplerate: int, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._stream = None
        self._lock = threading.Lock()

    def _ensure(self):
        if self._stream is None:
            import sounddevice as sd

            started = time.monotonic()
            self._stream = sd.RawOutputStream(samplerate=self.samplerate, channels=self.channels, dtype="int16")
            self._stream.start()
            log.info(
                "Аудиовыход %d Гц открыт за %.2f сек, задержка устройства %.2f сек",
                self.samplerate,
                time.monotonic() - started,
                getattr(self._stream, "latency", 0.0) or 0.0,
            )
            atexit.register(self.close)
        return self._stream

    @property
    def device_latency(self) -> float:
        return float(getattr(self._stream, "latency", 0.0) or 0.0)

    def play_stream(self, chunks: Iterable[bytes]) -> float:
        """Проигрывает PCM int16 по мере поступления. Возвращается, когда звук отыгран
        локально (без учёта сетевой задержки AirPlay). Возвращает длительность звука."""
        with self._lock:
            stream = self._ensure()
            frame = SAMPLE_WIDTH * self.channels
            pending = b""
            first_write: float | None = None
            total = 0
            for chunk in chunks:
                data = pending + chunk
                cut = len(data) - len(data) % frame  # не рвём сэмпл между кусками
                if cut:
                    if first_write is None:
                        first_write = time.monotonic()
                    stream.write(data[:cut])
                    total += cut
                pending = data[cut:]
            if first_write is None:
                return 0.0
            duration = total / frame / self.samplerate
            remaining = first_write + duration - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            return duration

    def play(self, pcm: bytes) -> float:
        return self.play_stream([pcm])

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("Аудиовыход закрылся с ошибкой: %s", exc)
            self._stream = None


_players: dict[int, PcmPlayer] = {}
_players_lock = threading.Lock()


def get_player(samplerate: int) -> PcmPlayer:
    with _players_lock:
        if samplerate not in _players:
            _players[samplerate] = PcmPlayer(samplerate)
        return _players[samplerate]


def warmup(samplerate: int) -> None:
    """Открыть поток заранее, чтобы первый ответ не ждал подключения к колонке."""
    get_player(samplerate).play(b"\x00\x00" * (samplerate // 20))  # 50 мс тишины
