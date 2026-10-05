"""Синтез речи.

По умолчанию системный `say` в macOS. Чтобы звук шёл в HomePod, выбери его
как устройство вывода звука на маке (Control Center -> Sound -> HomePod).
Свой движок (Piper, ElevenLabs) подключается реализацией класса с методом speak().
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from friday.config import settings


class Speaker(Protocol):
    def speak(self, text: str) -> None: ...


class MacSay:
    def __init__(self, voice: str = settings.tts_voice, rate: int = settings.tts_rate):
        self.voice = voice
        self.rate = rate

    def speak(self, text: str) -> None:
        if text:
            subprocess.run(["say", "-v", self.voice, "-r", str(self.rate), text], check=False)


class PrintOnly:
    def speak(self, text: str) -> None:
        pass


def default_speaker() -> Speaker:
    return MacSay() if shutil.which("say") else PrintOnly()
