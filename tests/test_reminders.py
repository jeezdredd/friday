from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from friday.integrations.apple_reminders import build_script
from friday.reminders import ReminderStore, describe_when, next_occurrence, parse_when
from friday.scheduler import ReminderScheduler
from friday.tools import load_all

TZ = "Asia/Tokyo"  # без перехода на летнее время, удобно для арифметики
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # 18:00 по Токио, понедельник


@pytest.fixture
def store(tmp_path):
    return ReminderStore(tmp_path / "test.db")


# ---------- разбор времени ----------


def test_parse_delay():
    assert parse_when(None, 20, TZ, NOW) == NOW + timedelta(minutes=20)


def test_parse_local_time_uses_home_timezone():
    assert parse_when("2026-10-05T18:30", None, TZ, NOW) == datetime(2026, 10, 5, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("when", "delay"),
    [("2026-10-05T17:00", None), (None, 0), (None, None)],
)
def test_parse_rejects_past_and_empty(when, delay):
    with pytest.raises(ValueError):
        parse_when(when, delay, TZ, NOW)


# ---------- повторы ----------


def test_daily_and_weekly():
    due = datetime(2026, 10, 5, 23, 0, tzinfo=UTC)  # 08:00 вторника по Токио
    assert next_occurrence(due, "daily", TZ) == due + timedelta(days=1)
    assert next_occurrence(due, "weekly", TZ) == due + timedelta(weeks=1)
    assert next_occurrence(due, "none", TZ) is None


def test_weekdays_skip_weekend():
    friday_8am = datetime(2026, 10, 9, 8, 0, tzinfo=ZoneInfo(TZ))
    nxt = next_occurrence(friday_8am.astimezone(UTC), "weekdays", TZ).astimezone(ZoneInfo(TZ))
    assert (nxt.weekday(), nxt.hour) == (0, 8)  # понедельник, 08:00


def test_daily_keeps_wall_clock_across_dst():
    berlin = "Europe/Berlin"  # 25 октября 2026 переход на зимнее время
    due = datetime(2026, 10, 24, 8, 0, tzinfo=ZoneInfo(berlin)).astimezone(UTC)
    nxt = next_occurrence(due, "daily", berlin).astimezone(ZoneInfo(berlin))
    assert (nxt.day, nxt.hour) == (25, 8)


# ---------- хранилище и планировщик ----------


def test_store_roundtrip_and_cancel(store):
    r = store.add("выключить духовку", NOW + timedelta(minutes=5))
    assert [x.id for x in store.pending()] == [r.id]
    assert store.find("духов")[0].id == r.id
    assert store.cancel(r.id)
    assert store.pending() == []
    assert not store.cancel(r.id)


def test_scheduler_fires_once(store, monkeypatch):
    monkeypatch.setattr("friday.scheduler.get_timezone", lambda: TZ)
    store.add("выключить духовку", NOW + timedelta(minutes=1))
    said = []
    sched = ReminderScheduler(said.append, store=store, notify=None)

    assert sched.tick(NOW) == []
    sched.tick(NOW + timedelta(minutes=1, seconds=5))
    sched.tick(NOW + timedelta(minutes=2))
    assert said == ["Напоминаю: выключить духовку."]
    assert store.pending() == []


def test_scheduler_recurring_reschedules(store, monkeypatch):
    monkeypatch.setattr("friday.scheduler.get_timezone", lambda: TZ)
    first = NOW + timedelta(minutes=1)
    store.add("выпить воду", first, "daily")
    sched = ReminderScheduler(lambda _: None, store=store, notify=None)
    sched.tick(first)
    (r,) = store.pending()
    assert r.due_at == first + timedelta(days=1)


def test_scheduler_marks_missed_and_skips_past_recurrences(store, monkeypatch):
    monkeypatch.setattr("friday.scheduler.get_timezone", lambda: TZ)
    store.add("размяться", NOW - timedelta(days=3), "daily")
    said = []
    ReminderScheduler(said.append, store=store, notify=None).tick(NOW)
    assert said == ["Пропущенное напоминание: размяться."]
    (r,) = store.pending()
    assert r.due_at > NOW  # не стреляет три раза подряд за пропущенные дни


def test_scheduler_survives_announce_failure(store, monkeypatch):
    monkeypatch.setattr("friday.scheduler.get_timezone", lambda: TZ)
    store.add("тест", NOW)

    def boom(_):
        raise RuntimeError("колонка недоступна")

    ReminderScheduler(boom, store=store, notify=None).tick(NOW)
    assert store.pending() == []  # отмечено, не будет повторяться бесконечно


# ---------- человеческое описание ----------


@pytest.mark.parametrize(
    ("due_local", "expected"),
    [
        (datetime(2026, 10, 5, 18, 20, tzinfo=ZoneInfo(TZ)), "через 20 мин, в 18:20"),
        (datetime(2026, 10, 5, 21, 0, tzinfo=ZoneInfo(TZ)), "сегодня в 21:00"),
        (datetime(2026, 10, 6, 9, 0, tzinfo=ZoneInfo(TZ)), "завтра в 09:00"),
        (datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo(TZ)), "в четверг в 10:00"),
        (datetime(2026, 11, 12, 8, 0, tzinfo=ZoneInfo(TZ)), "12 ноября в 08:00"),
    ],
)
def test_describe_when(due_local, expected):
    due = due_local.astimezone(UTC)
    assert describe_when(due, TZ, NOW) == expected


# ---------- инструменты ----------


def test_tools_end_to_end(monkeypatch):
    monkeypatch.setattr("friday.tools.reminders.get_timezone", lambda: TZ)
    reg = load_all()
    out, err = reg.execute("create_reminder", {"text": "позвонить маме", "delay_minutes": 30})
    assert not err and "позвонить маме" in out
    out, err = reg.execute("list_reminders", {"scope": "all"})
    assert not err and "позвонить маме" in out
    out, err = reg.execute("cancel_reminder", {"text_contains": "маме"})
    assert not err and out.startswith("Отменено")
    out, err = reg.execute("create_reminder", {"text": "x"})
    assert err  # ни when, ни delay_minutes


def test_apple_script_escapes_and_builds_date():
    script = build_script('Пятница "дом"', 'купить "молоко"', datetime(2026, 12, 31, 7, 5))  # noqa: DTZ001 - наивное местное время
    assert 'list "Пятница \\"дом\\""' in script
    assert 'name:"купить \\"молоко\\""' in script
    assert "set month of d to 12" in script and "set minutes of d to 5" in script
