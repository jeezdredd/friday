"""Фоновый планировщик: следит за напоминаниями и озвучивает их вовремя.

Работает, пока запущен процесс Пятницы. Напоминания, пропущенные пока процесс
был выключен, озвучиваются при старте с пометкой "пропущенное".
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from friday.config import settings
from friday.location import get_timezone
from friday.reminders import Reminder, ReminderStore, get_store, utcnow

log = logging.getLogger(__name__)

MISSED_AFTER = timedelta(minutes=5)


def announcement(reminder: Reminder, now: datetime) -> str:
    if now - reminder.due_at > MISSED_AFTER:
        return f"Пропущенное напоминание: {reminder.text}."
    return f"Напоминаю: {reminder.text}."


def notify_macos(text: str) -> None:
    """Дублируем в Центр уведомлений, на случай если ты не у колонки."""
    if not shutil.which("osascript"):
        return
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'display notification "{safe}" with title "Пятница" sound name "Glass"'],
        check=False,
        capture_output=True,
    )


class ReminderScheduler:
    def __init__(
        self,
        announce: Callable[[str], None],
        store: ReminderStore | None = None,
        interval: float | None = None,
        notify: Callable[[str], None] | None = notify_macos,
    ):
        self.announce = announce
        self.store = store
        self.interval = interval or settings.reminder_check_seconds
        self.notify = notify
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self, now: datetime | None = None) -> list[str]:
        """Один проход: озвучивает всё, что пора. Возвращает сказанное (удобно для тестов)."""
        store = self.store or get_store()
        now = now or utcnow()
        tz = get_timezone()
        said = []
        for reminder in store.due(now):
            text = announcement(reminder, now)
            # сначала отмечаем, потом говорим: упавшая озвучка не должна зациклить напоминание
            store.mark_fired(reminder, tz, now)
            log.info("Напоминание %s: %s", reminder.id, text)
            if self.notify:
                self.notify(text)
            try:
                self.announce(text)
            except Exception:
                log.exception("Не удалось озвучить напоминание")
            said.append(text)
        return said

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Ошибка планировщика")
            self._stop.wait(self.interval)

    def start(self) -> ReminderScheduler:
        self._thread = threading.Thread(target=self._run, name="reminders", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
