"""Зеркало напоминаний в приложение Apple «Напоминания» через AppleScript.

Включается через APPLE_REMINDERS_LIST=<имя списка>. Тогда напоминание появится
на iPhone, Apple Watch и в iCloud, а не только прозвучит дома.
При первом вызове macOS спросит разрешение на управление «Напоминаниями».
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime

log = logging.getLogger(__name__)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_script(list_name: str, title: str, due_local: datetime) -> str:
    # Дату собираем по компонентам: строковый парсинг дат в AppleScript зависит от локали системы.
    lst = _quote(list_name)
    return f"""
tell application "Reminders"
    if not (exists list {lst}) then make new list with properties {{name:{lst}}}
    set d to current date
    set day of d to 1
    set year of d to {due_local.year}
    set month of d to {due_local.month}
    set day of d to {due_local.day}
    set hours of d to {due_local.hour}
    set minutes of d to {due_local.minute}
    set seconds of d to 0
    make new reminder at end of list {lst} with properties {{name:{_quote(title)}, remind me date:d}}
end tell
"""


def add_reminder(list_name: str, title: str, due_local: datetime) -> bool:
    if not shutil.which("osascript"):
        return False
    result = subprocess.run(
        ["osascript", "-"],
        input=build_script(list_name, title, due_local),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        log.warning("Apple Reminders: %s", result.stderr.strip())
        return False
    return True
