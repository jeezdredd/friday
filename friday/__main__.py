"""Точка входа.

python -m friday            текстовый чат в терминале
python -m friday --speak    текстовый чат, ответы озвучиваются
python -m friday --voice    голосовой режим, wake word "Пятница"
python -m friday --ptt      голосовой режим push-to-talk (Enter)
python -m friday --tools    показать доступные инструменты
"""

from __future__ import annotations

import argparse
import json
import logging

from friday.agent import Agent
from friday.tools import load_all

EXIT_WORDS = {"exit", "quit", "выход", "пока"}


def _print_tool_call(name: str, args: dict) -> None:
    print(f"  [tool] {name}({json.dumps(args, ensure_ascii=False)})")


def text_loop(agent: Agent, speak: bool) -> None:
    speaker = None
    if speak:
        from friday.voice.tts import default_speaker

        speaker = default_speaker()

    print("Пятница на связи. /reset очистить контекст, exit выйти.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in EXIT_WORDS:
            break
        if text == "/reset":
            agent.reset()
            print("Контекст очищен.")
            continue
        answer = agent.ask(text)
        print(f"Пятница: {answer}")
        if speaker:
            speaker.speak(answer)


def _reply(agent: Agent, speaker, text: str) -> None:
    print(f"Ты: {text}")
    answer = agent.ask(text)
    print(f"Пятница: {answer}")
    speaker.speak(answer)


def ptt_loop(agent: Agent) -> None:
    from friday.voice.recorder import record_push_to_talk
    from friday.voice.stt import transcribe
    from friday.voice.tts import default_speaker

    speaker = default_speaker()
    print("Push-to-talk. Ctrl+C выход.")
    while True:
        try:
            audio = record_push_to_talk()
        except KeyboardInterrupt:
            print()
            break
        text = transcribe(audio)
        if not text:
            print("(ничего не расслышала)")
            continue
        _reply(agent, speaker, text)


def wake_loop(agent: Agent) -> None:
    import numpy as np

    from friday.config import settings
    from friday.voice.audio import MicStream
    from friday.voice.listener import Listener, chime, split_wake_command, strip_wake_word
    from friday.voice.stt import transcribe
    from friday.voice.tts import default_speaker
    from friday.voice.wakeword import create_detector

    speaker = default_speaker()
    print("Загружаю модели...")
    detector = create_detector()
    transcribe(np.zeros(16_000, dtype=np.float32))  # прогрев whisper

    with MicStream(frame_samples=detector.frame_samples) as mic:
        listener = Listener(mic, detector)
        print(f'Слушаю. Скажи "{settings.wake_word.capitalize()}". Ctrl+C выход.')
        try:
            while True:
                listener.wait_for_wake_word()
                chime()
                heard = transcribe(listener.record_phrase())
                addressed, text = split_wake_command(heard)
                if not addressed:
                    # детектор услышал похожее слово, но Whisper не подтвердил обращение
                    logging.getLogger(__name__).info("Ложное срабатывание: %r", heard)
                    listener.after_speaking()
                    continue
                if not text:
                    # сказали только "Пятница": отзываемся и ждём саму команду
                    speaker.speak("Да?")
                    listener.after_speaking()
                    text = transcribe(listener.record_phrase(with_preroll=False))
                    if not text:
                        continue

                _reply(agent, speaker, text)
                listener.after_speaking()

                # окно продолжения: можно ответить без повторного "Пятница"
                while settings.followup_seconds > 0:
                    audio = listener.record_phrase(with_preroll=False, start_timeout=settings.followup_seconds)
                    text = strip_wake_word(transcribe(audio)) if audio.size else ""
                    if not text:
                        break
                    _reply(agent, speaker, text)
                    listener.after_speaking()
        except KeyboardInterrupt:
            print()


def say_test(text: str) -> None:
    from friday.config import settings
    from friday.voice.speech_text import prepare_for_speech
    from friday.voice.tts import create_speaker

    speaker = create_speaker()
    stress = {"ElevenLabs": settings.elevenlabs_stress, "Silero": "plus"}.get(type(speaker).__name__, "none")
    print(f"Движок: {type(speaker).__name__}")
    print(f"В синтезатор уйдёт: {prepare_for_speech(text, stress=stress)}")
    speaker.speak(text)


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday")
    parser.add_argument("--voice", action="store_true", help='голосовой режим с wake word "Пятница"')
    parser.add_argument("--ptt", action="store_true", help="голосовой режим push-to-talk (Enter)")
    parser.add_argument("--speak", action="store_true", help="озвучивать ответы в текстовом режиме")
    parser.add_argument("--tools", action="store_true", help="список инструментов")
    parser.add_argument("--say", metavar="TEXT", help="озвучить текст без LLM, чтобы проверить произношение")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.say:
        say_test(args.say)
        return

    if args.tools:
        for t in load_all().all():
            print(f"{t.name}: {t.description.splitlines()[0]}")
        return

    agent = Agent(on_tool_call=_print_tool_call)
    if args.voice:
        wake_loop(agent)
    elif args.ptt:
        ptt_loop(agent)
    else:
        text_loop(agent, speak=args.speak)


if __name__ == "__main__":
    main()
