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
import threading
import time

from friday.agent import Agent
from friday.tools import load_all

EXIT_WORDS = {"exit", "quit", "выход", "пока"}

log = logging.getLogger("friday")


def _print_tool_call(name: str, args: dict) -> None:
    print(f"  [tool] {name}({json.dumps(args, ensure_ascii=False)})")


def _make_voice(agent: Agent):
    """Голосовой выход: ответы, заполнители во время работы инструментов, кеш коротких фраз."""
    from friday.voice.output import VoiceOutput
    from friday.voice.tts import create_speaker

    voice = VoiceOutput(create_speaker(), agent.registry)
    if hasattr(voice.speaker, "warmup"):
        # открываем аудиопоток к колонке сразу, а не на первом ответе
        threading.Thread(target=voice.speaker.warmup, daemon=True).start()
    voice.prefetch_async()

    # заполнитель запускается, как только модель начала вызывать инструмент (включая поиск)
    previous = agent.on_tool_start

    def on_tool_start(name: str) -> None:
        if previous:
            previous(name)
        voice.on_tool_call(name)

    agent.on_tool_start = on_tool_start
    return voice


def _start_reminders(announce):
    from friday.scheduler import ReminderScheduler

    return ReminderScheduler(announce).start()


def _reply(agent: Agent, voice, text: str, speaker_note: str | None = None) -> str:
    print(f"Ты: {text}")
    started = time.monotonic()
    if voice:
        voice.begin_request()
    answer = agent.ask(text, speaker_note=speaker_note)
    log.info("Ответ агента за %.2f сек", time.monotonic() - started)
    print(f"Пятница: {answer}")
    if voice:
        voice.speak(answer)
        log.info("Всего с конца фразы до конца речи: %.2f сек", time.monotonic() - started)
    return answer


def text_loop(agent: Agent, speak: bool) -> None:
    voice = _make_voice(agent) if speak else None

    def announce(text: str) -> None:
        print(f"\nПятница: {text}\n> ", end="", flush=True)
        if voice:
            voice.speak(text)

    _start_reminders(announce)
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
        _reply(agent, voice, text)


def ptt_loop(agent: Agent) -> None:
    from friday.voice.recorder import record_push_to_talk
    from friday.voice.stt import transcribe

    voice = _make_voice(agent)
    _start_reminders(lambda text: (print(f"\nПятница: {text}"), voice.speak(text)))
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
        _reply(agent, voice, text)


def _identity_gate(voice):
    """Голосовая идентификация: при первом запуске знакомимся, дальше узнаём владельца."""
    from friday.config import settings
    from friday.voice.speaker_id import IdentityGate, load_speaker_id, load_voiceprint

    if not settings.voice_id:
        return IdentityGate(None)
    if load_voiceprint() is None:
        from friday.enroll import run_enrollment

        print("\nПервый запуск: давай познакомимся, чтобы я узнавала тебя по голосу.")
        print("Пропустить можно через VOICE_ID=0 в .env.\n")
        if not run_enrollment(speak=voice.speak):
            print("Продолжаю без голосовой идентификации. Повторить: python -m friday.enroll")
            return IdentityGate(None)
    speaker_id = load_speaker_id()
    if speaker_id is None:
        return IdentityGate(None)
    print(f"Голосовая идентификация: {speaker_id.voiceprint.name}, порог {speaker_id.voiceprint.threshold:.2f}")
    return IdentityGate(speaker_id, settings.voice_id_policy, settings.greet_after_minutes)


def greeting_for(name: str) -> str:
    return f"Приветствую, {name}. Чем могу помочь?"


def wake_loop(agent: Agent) -> None:
    import numpy as np

    from friday.config import settings
    from friday.voice.audio import MicStream, output_device_name
    from friday.voice.listener import Listener, is_self_echo, split_wake_command, strip_wake_word
    from friday.voice.stt import transcribe
    from friday.voice.wakeword import create_detector

    voice = _make_voice(agent)
    gate = _identity_gate(voice)
    owner = gate.speaker_id.voiceprint.name if gate.enabled else ""
    if owner:
        voice.prefetch_async(extra=[greeting_for(owner)])
    print("Загружаю модели...")
    detector = create_detector()
    transcribe(np.zeros(16_000, dtype=np.float32))  # прогрев whisper
    if gate.enabled:
        gate.identify(np.zeros(16_000, dtype=np.float32))  # прогрев модели голоса

    def timed_transcribe(audio) -> str:
        started = time.monotonic()
        text = transcribe(audio)
        log.info("Распознавание: %.2f сек", time.monotonic() - started)
        return text

    def note_for(identity, greet: bool) -> str | None:
        note = gate.context_note(identity)
        if greet and identity.known:
            note = (
                note or ""
            ) + f" Это первое обращение за сессию: начни ответ с короткого приветствия по имени, {identity.name}."
        return note

    with MicStream(frame_samples=detector.frame_samples) as mic:
        listener = Listener(mic, detector)

        def announce(text: str) -> None:
            print(f"Пятница: {text}")
            with listener.muted():
                voice.speak(text)

        _start_reminders(announce)
        engine = type(voice.speaker).__name__
        print(f"Синтез: {engine}. Вывод: {output_device_name() or '?'} (задержка {listener.latency:.1f} сек)")
        print(f'Слушаю. Скажи "{settings.wake_word.capitalize()}". Ctrl+C выход.')
        if settings.startup_greeting:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from friday.location import get_timezone

            with listener.muted():
                voice.greet(datetime.now(ZoneInfo(get_timezone())).hour)
        try:
            while True:
                listener.wait_for_wake_word()
                listener.chime()
                print("(услышала обращение)")
                audio = listener.record_phrase()
                heard = timed_transcribe(audio)
                addressed, text = split_wake_command(heard)
                if not addressed:
                    # детектор услышал похожее слово, но Whisper не подтвердил обращение
                    log.info("Ложное срабатывание: %r", heard)
                    listener.reset()
                    continue

                identity = gate.identify(audio)
                if not gate.allowed(identity):
                    log.info("Голос не владельца, игнорирую (VOICE_ID_POLICY=owner_only)")
                    listener.reset()
                    continue
                greet = gate.should_greet(identity)

                if not text:
                    # сказали только "Пятница": отзываемся и ждём саму команду
                    if greet:
                        voice.speak_short(greeting_for(identity.name))
                        greet = False  # уже поздоровались, в ответе повторять не нужно
                    else:
                        voice.ack()
                    listener.after_speaking()
                    audio = listener.record_phrase(with_preroll=False)
                    text = timed_transcribe(audio)
                    if not text:
                        continue
                    second = gate.identify(audio)
                    if second.verification and second.verification.reliable:
                        identity = second
                    if not gate.allowed(identity):
                        listener.reset()
                        continue

                answer = _reply(agent, voice, text, note_for(identity, greet))
                listener.after_speaking()

                # окно продолжения: можно ответить без повторного "Пятница"
                while settings.followup_seconds > 0:
                    audio = listener.record_phrase(with_preroll=False, start_timeout=settings.followup_seconds)
                    text = strip_wake_word(timed_transcribe(audio)) if audio.size else ""
                    if not text:
                        break
                    if is_self_echo(text, answer):
                        log.info("Пропускаю эхо собственного ответа: %r", text)
                        continue
                    identity = gate.identify(audio)
                    if not gate.allowed(identity):
                        log.info("Продолжение чужим голосом, игнорирую")
                        break
                    gate.should_greet(identity)  # обновляем время последнего контакта
                    answer = _reply(agent, voice, text, note_for(identity, greet=False))
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
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="-v: логи и тайминги Пятницы, -vv: плюс все библиотеки"
    )
    args = parser.parse_args()

    # -v показывает только логи самой Пятницы (тайминги, инструменты), без запросов httpx и whisper
    logging.basicConfig(
        level=logging.INFO if args.verbose >= 2 else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if args.verbose:
        logging.getLogger("friday").setLevel(logging.INFO)

    if args.say:
        say_test(args.say)
        return

    if args.tools:
        for t in load_all().all():
            print(f"{t.name}: {t.description.splitlines()[0]}")
        return

    def print_server_tool(name: str) -> None:
        if name == "web_search":
            print("  [tool] web_search")

    agent = Agent(on_tool_call=_print_tool_call, on_tool_start=print_server_tool)
    if args.voice:
        wake_loop(agent)
    elif args.ptt:
        ptt_loop(agent)
    else:
        text_loop(agent, speak=args.speak)


if __name__ == "__main__":
    main()
