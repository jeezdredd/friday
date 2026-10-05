"""Знакомство: запись отпечатка голоса владельца.

    python -m friday.enroll

Запускается сам при первом старте голосового режима, если отпечатка ещё нет.
Пятница просит прочитать вслух несколько фраз, проверяет, что они записались
чисто и похожи друг на друга, и сохраняет отпечаток в FRIDAY_DATA_DIR/voiceprint.json.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import numpy as np

from friday.config import settings
from friday.voice.audio import SAMPLE_RATE, MicStream, output_latency, rms
from friday.voice.listener import Endpointer, NoiseFloor
from friday.voice.speaker_id import (
    Embedder,
    build_voiceprint,
    calibrate_threshold,
    load_speaker_id,
    load_voiceprint,
    save_voiceprint,
)

log = logging.getLogger(__name__)

PHRASES = (
    "Пятница, это я. Запомни мой голос, пожалуйста.",
    "Сегодня отличный день, чтобы сделать что-нибудь новое.",
    "Включи свет, поставь таймер на десять минут и найди свежие новости.",
    "Мне нравится, когда всё работает быстро и без лишних вопросов.",
    "Съешь же ещё этих мягких французских булок, да выпей чаю.",
)
MIN_PHRASE_SECONDS = 1.5
OUTLIER_SCORE = 0.5  # фраза заметно не похожа на остальные: шум, кашель, чужой голос
MAX_ATTEMPTS = 3


def measure_noise(mic: MicStream, seconds: float = 1.0) -> NoiseFloor:
    noise = NoiseFloor()
    frames = int(seconds * SAMPLE_RATE / mic.frame_samples)
    for _ in range(frames):
        noise.update(rms(mic.read()))
    return noise


def record_utterance(mic: MicStream, noise: NoiseFloor, start_timeout: float = 8.0) -> np.ndarray:
    ep = Endpointer(
        frame_seconds=mic.frame_samples / SAMPLE_RATE,
        noise_floor=noise.level,
        silence_seconds=1.0,
        max_seconds=15,
        start_timeout=start_timeout,
    )
    frames = []
    while True:
        frame = mic.read()
        frames.append(frame)
        if ep.feed(rms(frame)):
            break
    return np.concatenate(frames) if ep.speech_started else np.zeros(0, dtype=np.float32)


def find_outliers(embeddings: list[np.ndarray]) -> list[int]:
    _, scores = calibrate_threshold(embeddings)
    return [i for i, s in enumerate(scores) if s < OUTLIER_SCORE]


def run_enrollment(name: str | None = None, speak=None, mic: MicStream | None = None) -> bool:
    """Интерактивное знакомство. speak(text) озвучивает подсказки, если передан."""

    def say(text: str) -> None:
        print(f"Пятница: {text}")
        if speak:
            try:
                speak(text)
                # AirPlay доигрывает хвост ещё пару секунд: не пишем саму Пятницу как фон или фразу
                time.sleep(output_latency(override=settings.output_latency))
            except Exception as exc:  # noqa: BLE001
                log.warning("Не удалось озвучить: %s", exc)

    default_name = settings.user_name or (load_voiceprint().name if load_voiceprint() else "")
    if not name:
        hint = f" [{default_name}]" if default_name else ""
        name = input(f"Как тебя зовут?{hint} ").strip() or default_name
    if not name:
        print("Без имени не получится, запусти ещё раз.")
        return False

    print("Загружаю модель голосовой идентификации...")
    embedder = Embedder()
    say(f"Приятно познакомиться, {name}. Прочитай вслух несколько фраз обычным голосом, как говоришь со мной.")
    print("Совет: читай с того места, откуда обычно со мной говоришь, и в обычной обстановке.")

    own_mic = mic is None
    mic = mic or MicStream()
    if own_mic:
        mic.__enter__()
    try:
        time.sleep(0.3)
        mic.flush()
        print("Секунду тишины, замеряю фон...")
        noise = measure_noise(mic)
        embeddings: list[np.ndarray] = [np.zeros(0)] * len(PHRASES)
        todo = list(range(len(PHRASES)))

        for _attempt in range(MAX_ATTEMPTS):
            for i in todo:
                while True:
                    mic.flush()
                    print(f'\n[{i + 1}/{len(PHRASES)}] Прочитай: "{PHRASES[i]}"')
                    audio = record_utterance(mic, noise)
                    seconds = audio.size / SAMPLE_RATE
                    if seconds < MIN_PHRASE_SECONDS:
                        print("Не расслышала, давай ещё раз чуть громче.")
                        continue
                    embeddings[i] = embedder.embed(audio)
                    print(f"Записано, {seconds:.1f} сек.")
                    break
            todo = find_outliers(embeddings)
            if not todo:
                break
            print(f"\nФразы {', '.join(str(i + 1) for i in todo)} не похожи на остальные, повторим их.")
        else:
            say("Записи получились слишком разными. Попробуем позже в более тихом месте.")
            return False

        vp = build_voiceprint(name, embeddings)
        path = save_voiceprint(vp)
        load_speaker_id.cache_clear()
        log.info("Отпечаток: порог %.2f, сходство фраз %s", vp.threshold, vp.self_similarity)
        print(f"\nОтпечаток сохранён: {path} (порог {vp.threshold:.2f})")
        say(f"Готово, {name}. Теперь я узнаю тебя по голосу.")
        return True
    finally:
        if own_mic:
            mic.__exit__(None, None, None)


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday.enroll", description="Записать отпечаток голоса владельца")
    parser.add_argument("--name", help="имя владельца")
    parser.add_argument("--silent", action="store_true", help="не озвучивать подсказки")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.verbose:
        logging.getLogger("friday").setLevel(logging.INFO)

    speak = None
    if not args.silent:
        from friday.voice.tts import create_speaker

        speak = create_speaker().speak
    sys.exit(0 if run_enrollment(args.name, speak) else 1)


if __name__ == "__main__":
    main()
