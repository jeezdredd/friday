"""Управление маком: громкость, яркость, приложения, тёмная тема, батарея, экран,
Быстрые команды. На других ОС модуль ничего не регистрирует."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from friday.integrations import macos
from friday.tools import tool


def mac_tool(**kwargs):
    """Регистрирует инструмент только на macOS; на других системах функция остаётся обычной."""
    if macos.IS_MAC:
        return tool(**kwargs)
    return lambda f: f


# ---------- звук ----------


@mac_tool(filler="")
def set_volume(
    level: Annotated[int | None, "Громкость 0-100"] = None,
    change: Annotated[int | None, "Изменить на столько пунктов: +10 громче, -10 тише"] = None,
    mute: Annotated[bool | None, "true = выключить звук, false = включить обратно"] = None,
) -> dict[str, Any]:
    """Громкость мака (и HomePod, если звук идёт на него). "Громче", "тише", "на 30", "выключи звук".
    Для "громче/тише" без числа используй change ±10."""
    if mute is not None:
        macos.set_muted(mute)
    if level is not None:
        macos.set_volume(level)
    elif change is not None:
        current = macos.get_volume()["level"] or 0
        macos.set_volume(current + change)
    return macos.get_volume()


@mac_tool(filler="")
def get_volume() -> dict[str, Any]:
    """Текущая громкость и выключен ли звук."""
    return macos.get_volume()


# ---------- экран ----------


@mac_tool(filler="")
def set_brightness(
    level: Annotated[int | None, "Яркость встроенного дисплея 0-100"] = None,
    change: Annotated[Literal["up", "down"] | None, "Ярче или темнее на пару шагов"] = None,
) -> str:
    """Яркость встроенного дисплея мака. Внешние мониторы так не управляются."""
    if level is not None:
        macos.set_brightness(level)
        return f"Яркость около {level}%"
    if change is not None:
        macos.change_brightness(2 if change == "up" else -2)
        return "Ярче" if change == "up" else "Темнее"
    raise ValueError("Укажи level или change")


@mac_tool(filler="")
def set_dark_mode(mode: Literal["on", "off", "toggle"] = "toggle") -> str:
    """Включить или выключить тёмную тему macOS."""
    return "Тёмная тема включена" if macos.set_dark_mode(mode) else "Светлая тема включена"


@mac_tool(filler="")
def screen_action(action: Literal["sleep_display", "lock"]) -> str:
    """Погасить экран или заблокировать мак."""
    if action == "lock":
        macos.lock_screen()
        return "Заблокировано"
    macos.sleep_display()
    return "Экран погашен"


# ---------- приложения ----------


@mac_tool(filler="")
def open_app(name: Annotated[str, "Название приложения по-английски, как в папке Программы: Safari, Telegram"]) -> str:
    """Открыть приложение на маке или переключиться на него, если уже открыто."""
    return f"Открыто: {macos.open_app(name)}"


@mac_tool(filler="")
def quit_app(name: Annotated[str, "Название запущенного приложения"]) -> str:
    """Закрыть приложение. Если есть несохранённое, приложение само спросит, ничего не теряется."""
    return f"Закрыто: {macos.quit_app(name)}"


@mac_tool(filler="")
def list_running_apps() -> dict[str, Any]:
    """Какие приложения сейчас открыты и какое на переднем плане."""
    return {"running": macos.running_apps(), "frontmost": macos.frontmost_app()}


@mac_tool(filler="")
def open_url(url: Annotated[str, "Полная ссылка http(s)"]) -> str:
    """Открыть сайт в браузере по умолчанию: "открой ютуб" -> https://youtube.com."""
    macos.open_url(url)
    return "Открыто"


# ---------- система ----------


@mac_tool(filler="")
def get_battery() -> dict[str, Any]:
    """Заряд батареи мака и идёт ли зарядка."""
    info = macos.battery()
    return info or {"battery": "нет, это стационарный мак"}


# ---------- Быстрые команды ----------


@mac_tool(filler="")
def list_shortcuts() -> list[str]:
    """Быстрые команды пользователя (приложение Команды). Через них доступны фокусы, сцены дома и многое другое."""
    return macos.list_shortcuts()


@mac_tool(filler="Запускаю.")
def run_shortcut(
    name: Annotated[str, "Название быстрой команды, точное или близкое"],
    input_text: Annotated[str | None, "Текст на вход команде, если она его ждёт"] = None,
) -> str:
    """Запустить быструю команду пользователя. Если не знаешь точное название, сначала list_shortcuts."""
    return macos.run_shortcut(name, input_text)
