"""Напоминания и таймеры."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from friday.config import settings
from friday.integrations import apple_reminders
from friday.location import get_timezone
from friday.reminders import describe_when, get_store, parse_when, utcnow
from friday.tools import tool


@tool(filler="")
def create_reminder(
    text: Annotated[str, "Что напомнить, коротко и по-русски, как это будет произнесено: 'выключить духовку'"],
    when: Annotated[str | None, "Точное локальное время дома в ISO, например 2026-10-05T18:30"] = None,
    delay_minutes: Annotated[float | None, "Через сколько минут. Для 'через 20 минут' и таймеров"] = None,
    recurrence: Literal["none", "daily", "weekdays", "weekly"] = "none",
) -> dict[str, Any]:
    """Создать напоминание или таймер. Пятница скажет его голосом в нужный момент.
    Для относительного времени ("через полчаса", "таймер на 10 минут") передавай delay_minutes,
    для конкретного ("завтра в 9", "в 18:30") передавай when. Ровно одно из двух."""
    tz = get_timezone()
    due = parse_when(when, delay_minutes, tz)
    reminder = get_store().add(text, due, recurrence)
    result: dict[str, Any] = {
        "id": reminder.id,
        "text": reminder.text,
        "when": describe_when(reminder.due_at, tz),
        "recurrence": recurrence,
    }
    if settings.apple_reminders_list and recurrence == "none":
        result["apple_reminders"] = apple_reminders.add_reminder(
            settings.apple_reminders_list, reminder.text, reminder.local_due(tz).replace(tzinfo=None)
        )
    return result


@tool(filler="")
def list_reminders(
    scope: Annotated[
        Literal["today", "upcoming", "all"], "today: до конца дня, upcoming: ближайшие 7 дней"
    ] = "upcoming",
) -> list[dict[str, Any]]:
    """Список активных напоминаний и таймеров."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    tz = get_timezone()
    now = utcnow()
    until = None
    if scope == "today":
        local = now.astimezone(ZoneInfo(tz))
        until = local.replace(hour=23, minute=59, second=59)
    elif scope == "upcoming":
        until = now + timedelta(days=7)
    return [
        {"id": r.id, "text": r.text, "when": describe_when(r.due_at, tz), "recurrence": r.recurrence}
        for r in get_store().pending(until=until)
    ]


@tool(filler="")
def cancel_reminder(
    reminder_id: Annotated[int | None, "id напоминания из list_reminders"] = None,
    text_contains: Annotated[str | None, "Часть текста напоминания, если id неизвестен"] = None,
) -> str:
    """Отменить напоминание или таймер по id или по части текста."""
    store = get_store()
    if reminder_id is not None:
        return "Отменено" if store.cancel(reminder_id) else f"Активного напоминания с id {reminder_id} нет"
    if not text_contains:
        raise ValueError("Укажи reminder_id или text_contains")
    matches = store.find(text_contains)
    if not matches:
        return "Ничего похожего не нашла"
    if len(matches) > 1:
        options = "; ".join(f"{r.id}: {r.text}" for r in matches)
        return f"Подходит несколько, уточни какое: {options}"
    store.cancel(matches[0].id)
    return f"Отменено: {matches[0].text}"
