"""Напоминания и таймеры.

Хранятся в SQLite (FRIDAY_DATA_DIR/friday.db), время в UTC. Модель передаёт
либо локальное время дома ("2026-10-05T18:30"), либо задержку в минутах,
чтобы не заниматься арифметикой с датами самой.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from friday.config import settings
from friday.location import get_timezone

Recurrence = Literal["none", "daily", "weekdays", "weekly"]
RECURRENCES: tuple[str, ...] = ("none", "daily", "weekdays", "weekly")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT    NOT NULL,
    due_at      TEXT    NOT NULL,          -- ISO 8601, UTC
    recurrence  TEXT    NOT NULL DEFAULT 'none',
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | done | cancelled
    created_at  TEXT    NOT NULL,
    fired_at    TEXT
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (status, due_at);
"""


@dataclass(frozen=True)
class Reminder:
    id: int
    text: str
    due_at: datetime  # aware, UTC
    recurrence: str
    status: str

    def local_due(self, tz: str | None = None) -> datetime:
        return self.due_at.astimezone(ZoneInfo(tz or get_timezone()))


def utcnow() -> datetime:
    return datetime.now(UTC)


def next_occurrence(due: datetime, recurrence: str, tz: str) -> datetime | None:
    """Следующее срабатывание повторяющегося напоминания. Считается в местном времени,
    чтобы "каждый день в 8 утра" оставалось в 8 утра и после перехода на летнее время."""
    if recurrence == "none":
        return None
    local = due.astimezone(ZoneInfo(tz))
    if recurrence == "daily":
        nxt = local + timedelta(days=1)
    elif recurrence == "weekly":
        nxt = local + timedelta(weeks=1)
    elif recurrence == "weekdays":
        nxt = local + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
    else:
        raise ValueError(f"Неизвестный повтор: {recurrence}")
    # пересобираем, чтобы wall-clock время сохранилось при смене смещения
    nxt = nxt.replace(tzinfo=None).replace(tzinfo=ZoneInfo(tz))
    return nxt.astimezone(UTC)


def parse_when(when: str | None, delay_minutes: float | None, tz: str, now: datetime | None = None) -> datetime:
    """Переводит то, что передала модель, в момент времени UTC."""
    now = now or utcnow()
    if delay_minutes is not None:
        if delay_minutes <= 0:
            raise ValueError("Задержка должна быть больше нуля")
        return now + timedelta(minutes=delay_minutes)
    if not when:
        raise ValueError("Укажи when (локальное время) или delay_minutes")
    dt = datetime.fromisoformat(when.strip().replace(" ", "T"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    dt = dt.astimezone(UTC)
    if dt <= now:
        raise ValueError(f"Время {when} уже прошло")
    return dt


class ReminderStore:
    def __init__(self, path: Path | None = None):
        self.path = path or settings.data_dir / "friday.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()  # планировщик и агент работают из разных потоков
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(r: sqlite3.Row) -> Reminder:
        return Reminder(r["id"], r["text"], datetime.fromisoformat(r["due_at"]), r["recurrence"], r["status"])

    def add(self, text: str, due_at: datetime, recurrence: str = "none") -> Reminder:
        if recurrence not in RECURRENCES:
            raise ValueError(f"recurrence должен быть одним из {RECURRENCES}")
        with self._lock, self._connect() as db:
            cur = db.execute(
                "INSERT INTO reminders (text, due_at, recurrence, created_at) VALUES (?, ?, ?, ?)",
                (text.strip(), due_at.astimezone(UTC).isoformat(), recurrence, utcnow().isoformat()),
            )
            return Reminder(cur.lastrowid, text.strip(), due_at.astimezone(UTC), recurrence, "pending")

    def pending(self, until: datetime | None = None) -> list[Reminder]:
        sql = "SELECT * FROM reminders WHERE status = 'pending'"
        params: tuple = ()
        if until is not None:
            sql += " AND due_at <= ?"
            params = (until.astimezone(UTC).isoformat(),)
        with self._lock, self._connect() as db:
            return [self._row(r) for r in db.execute(sql + " ORDER BY due_at", params)]

    def due(self, now: datetime | None = None) -> list[Reminder]:
        return self.pending(until=now or utcnow())

    def get(self, reminder_id: int) -> Reminder | None:
        with self._lock, self._connect() as db:
            r = db.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
            return self._row(r) if r else None

    def find(self, text_contains: str) -> list[Reminder]:
        needle = text_contains.lower()
        return [r for r in self.pending() if needle in r.text.lower()]

    def cancel(self, reminder_id: int) -> bool:
        with self._lock, self._connect() as db:
            cur = db.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'", (reminder_id,)
            )
            return cur.rowcount > 0

    def mark_fired(self, reminder: Reminder, tz: str, now: datetime | None = None) -> Reminder | None:
        """Отмечает срабатывание. Для повторяющихся переносит на следующий раз
        (пропуская прошедшие, если процесс долго не работал) и возвращает обновлённое."""
        now = now or utcnow()
        nxt = next_occurrence(reminder.due_at, reminder.recurrence, tz)
        while nxt is not None and nxt <= now:
            nxt = next_occurrence(nxt, reminder.recurrence, tz)
        with self._lock, self._connect() as db:
            if nxt is None:
                db.execute(
                    "UPDATE reminders SET status = 'done', fired_at = ? WHERE id = ?",
                    (now.isoformat(), reminder.id),
                )
                return None
            db.execute(
                "UPDATE reminders SET due_at = ?, fired_at = ? WHERE id = ?",
                (nxt.isoformat(), now.isoformat(), reminder.id),
            )
        return Reminder(reminder.id, reminder.text, nxt, reminder.recurrence, "pending")


_store: ReminderStore | None = None


def get_store() -> ReminderStore:
    global _store
    if _store is None or _store.path != settings.data_dir / "friday.db":
        _store = ReminderStore()
    return _store


# ---------- как называть время голосом ----------

_WEEKDAYS = ("понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье")
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip


def describe_when(due: datetime, tz: str, now: datetime | None = None) -> str:
    """Человеческое описание срока для модели: "сегодня в 18:30", "завтра в 09:00",
    "в среду в 10:00", "12 ноября в 08:00". Модель сама переведёт числа в слова."""
    now_local = (now or utcnow()).astimezone(ZoneInfo(tz))
    local = due.astimezone(ZoneInfo(tz))
    hm = local.strftime("%H:%M")
    days = (local.date() - now_local.date()).days
    if days == 0:
        delta = local - now_local
        if delta < timedelta(hours=1):
            minutes = max(1, round(delta.total_seconds() / 60))
            return f"через {minutes} мин, в {hm}"
        return f"сегодня в {hm}"
    if days == 1:
        return f"завтра в {hm}"
    if 1 < days < 7:
        return f"в {_WEEKDAYS[local.weekday()]} в {hm}"
    return f"{local.day} {_MONTHS[local.month - 1]} в {hm}"
