"""Точка входа.

python -m friday            текстовый чат в терминале
python -m friday --speak    текстовый чат, ответы озвучиваются
python -m friday --voice    голосовой режим (push-to-talk)
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


def voice_loop(agent: Agent) -> None:
    from friday.voice.recorder import record_push_to_talk
    from friday.voice.stt import transcribe
    from friday.voice.tts import default_speaker

    speaker = default_speaker()
    print("Голосовой режим. Ctrl+C выход.")
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
        print(f"Ты: {text}")
        answer = agent.ask(text)
        print(f"Пятница: {answer}")
        speaker.speak(answer)


def main() -> None:
    parser = argparse.ArgumentParser(prog="friday")
    parser.add_argument("--voice", action="store_true", help="голосовой режим")
    parser.add_argument("--speak", action="store_true", help="озвучивать ответы в текстовом режиме")
    parser.add_argument("--tools", action="store_true", help="список инструментов")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.tools:
        for t in load_all().all():
            print(f"{t.name}: {t.description.splitlines()[0]}")
        return

    agent = Agent(on_tool_call=_print_tool_call)
    if args.voice:
        voice_loop(agent)
    else:
        text_loop(agent, speak=args.speak)


if __name__ == "__main__":
    main()
