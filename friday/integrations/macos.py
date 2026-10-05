"""Низкоуровневое управление macOS: громкость, яркость, приложения, системные действия.

Только системные утилиты (osascript, open, pmset, shortcuts), без сторонних пакетов.
Аргументы всегда передаются списком, без shell, строки для AppleScript экранируются.

Разрешения macOS (спросит при первом использовании для Терминала или PyCharm):
- Automation: управление System Events и приложениями через AppleScript
- Accessibility: эмуляция клавиш (яркость, блокировка экрана)
"""

from __future__ import annotations

import difflib
import re
import subprocess
import sys
from pathlib import Path

from friday.tools.registry import ToolError

IS_MAC = sys.platform == "darwin"

APP_DIRS = (
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
)


class MacError(ToolError):
    pass


_PERMISSION_HINTS = (
    (
        ("assistive access", "-1719", "-25211"),
        (
            "Нет доступа к управлению клавиатурой. Разреши Терминалу (или PyCharm) в "
            "Системные настройки, Конфиденциальность и безопасность, Универсальный доступ."
        ),
    ),
    (
        ("not authorized to send apple events", "-1743", "not allowed to send"),
        (
            "Нет разрешения управлять приложениями. Разреши в "
            "Системные настройки, Конфиденциальность и безопасность, Автоматизация."
        ),
    ),
)

# Частые разговорные названия. Применяются, только если такое приложение установлено.
APP_ALIASES = {
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "settings": "System Settings",
    "systempreferences": "System Settings",
    "music": "Music",
    "applemusic": "Music",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "teams": "Microsoft Teams",
    "outlook": "Microsoft Outlook",
}


def run(args: list[str], input_text: str | None = None, timeout: float = 15) -> str:
    try:
        result = subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise MacError(f"Команда {args[0]} не найдена, это точно macOS?") from exc
    except subprocess.TimeoutExpired as exc:
        raise MacError(f"{args[0]} не ответил за {timeout:.0f} сек") from exc
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        low = err.lower()
        for markers, hint in _PERMISSION_HINTS:
            if any(m in low for m in markers):
                raise MacError(hint)
        raise MacError(err or f"{args[0]} завершился с кодом {result.returncode}")
    return result.stdout.strip()


def osascript(script: str, timeout: float = 15) -> str:
    return run(["osascript", "-"], input_text=script, timeout=timeout)


def quote(text: str) -> str:
    """Строковый литерал AppleScript."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------- громкость ----------


def get_volume() -> dict:
    out = osascript(
        'set s to get volume settings\nreturn (output volume of s as text) & "," & (output muted of s as text)'
    )
    level, muted = out.split(",")
    return {"level": None if level == "missing value" else int(level), "muted": muted.strip() == "true"}


def set_volume(level: int) -> None:
    level = max(0, min(100, int(level)))
    osascript(f"set volume output volume {level}\nset volume output muted false")


def set_muted(muted: bool) -> None:
    osascript(f"set volume output muted {'true' if muted else 'false'}")


# ---------- яркость ----------
#
# Эмуляция клавиш яркости (key code 144/145) на маках с Apple Silicon не работает,
# а утилита brightness там молча ничего не делает. Надёжный способ: системный фреймворк
# DisplayServices, через него яркость меняют MonitorControl и подобные утилиты.
# Он приватный, но стабилен много версий macOS и не требует разрешений.
# Работает для встроенного дисплея (и Apple Studio Display / Pro Display XDR).

CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
DISPLAY_SERVICES = "/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices"
BRIGHTNESS_TOLERANCE = 0.03  # насколько прочитанное значение может отличаться от заданного


class DisplayBrightness:
    """Яркость дисплея через DisplayServices. cg и ds можно подменить в тестах."""

    def __init__(self, cg=None, ds=None):
        import ctypes

        self._ctypes = ctypes
        self.cg = cg or ctypes.CDLL(CORE_GRAPHICS)
        self.ds = ds or ctypes.CDLL(DISPLAY_SERVICES)
        u32, f32 = ctypes.c_uint32, ctypes.c_float
        self.cg.CGMainDisplayID.restype = u32
        self.cg.CGGetOnlineDisplayList.argtypes = [u32, ctypes.POINTER(u32), ctypes.POINTER(u32)]
        self.cg.CGGetOnlineDisplayList.restype = ctypes.c_int32
        self.cg.CGDisplayIsBuiltin.argtypes = [u32]
        self.cg.CGDisplayIsBuiltin.restype = u32
        self.ds.DisplayServicesGetBrightness.argtypes = [u32, ctypes.POINTER(f32)]
        self.ds.DisplayServicesGetBrightness.restype = ctypes.c_int
        self.ds.DisplayServicesSetBrightness.argtypes = [u32, f32]
        self.ds.DisplayServicesSetBrightness.restype = ctypes.c_int

    def displays(self) -> list[int]:
        ct = self._ctypes
        ids = (ct.c_uint32 * 16)()
        count = ct.c_uint32(0)
        if self.cg.CGGetOnlineDisplayList(16, ids, ct.byref(count)) != 0:
            return [self.cg.CGMainDisplayID()]
        return list(ids[: count.value])

    def target(self) -> int:
        """Встроенный дисплей, если он есть, иначе главный."""
        displays = self.displays()
        builtin = [d for d in displays if self.cg.CGDisplayIsBuiltin(d)]
        return builtin[0] if builtin else self.cg.CGMainDisplayID()

    def get(self, display: int | None = None) -> float:
        value = self._ctypes.c_float(-1.0)
        display = self.target() if display is None else display
        if self.ds.DisplayServicesGetBrightness(display, self._ctypes.byref(value)) != 0 or value.value < 0:
            raise MacError("Этот дисплей не даёт управлять яркостью программно (обычно это внешний монитор)")
        return float(value.value)

    def set(self, level: float, display: int | None = None) -> float:
        """Ставит яркость 0..1 и возвращает прочитанное обратно значение."""
        display = self.target() if display is None else display
        level = max(0.0, min(1.0, level))
        if self.ds.DisplayServicesSetBrightness(display, level) != 0:
            raise MacError("Не получилось изменить яркость этого дисплея")
        actual = self.get(display)
        if abs(actual - level) > BRIGHTNESS_TOLERANCE:
            raise MacError(f"Яркость не изменилась как нужно: сейчас {round(actual * 100)}%")
        return actual


_display: DisplayBrightness | None = None


def _brightness() -> DisplayBrightness:
    global _display
    if _display is None:
        try:
            _display = DisplayBrightness()
        except OSError as exc:
            raise MacError("Управление яркостью недоступно на этом маке") from exc
    return _display


def get_brightness() -> int:
    return round(_brightness().get() * 100)


def set_brightness(level_pct: int) -> int:
    """Возвращает реальную яркость после изменения, в процентах."""
    return round(_brightness().set(level_pct / 100) * 100)


def change_brightness(delta_pct: int) -> int:
    return set_brightness(get_brightness() + delta_pct)


# ---------- приложения ----------


def installed_apps(dirs: tuple[Path, ...] = APP_DIRS) -> dict[str, Path]:
    apps: dict[str, Path] = {}
    for d in dirs:
        if d.is_dir():
            for p in d.glob("*.app"):
                apps.setdefault(p.stem, p)
    return apps


def _norm(name: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]", "", name.lower())


def resolve_app(name: str, apps: dict[str, Path] | None = None) -> str:
    """Находит установленное приложение по примерному названию: "vs code" -> "Visual Studio Code"."""
    apps = installed_apps() if apps is None else apps
    wanted = _norm(name)
    by_norm = {_norm(n): n for n in apps}
    if wanted in by_norm:
        return by_norm[wanted]
    alias = APP_ALIASES.get(wanted)
    if alias and alias in apps:
        return alias
    starts = [n for k, n in by_norm.items() if k.startswith(wanted)]
    if len(starts) == 1:
        return starts[0]
    contains = [n for k, n in by_norm.items() if wanted and wanted in k]
    if len(contains) == 1:
        return contains[0]
    acronym = [n for n in apps if _norm("".join(w[0] for w in re.findall(r"[A-Za-zА-Яа-я]+", n))) == wanted]
    if len(acronym) == 1:
        return acronym[0]
    close = difflib.get_close_matches(wanted, list(by_norm), n=3, cutoff=0.6)
    if len(close) == 1 or (close and difflib.SequenceMatcher(None, wanted, close[0]).ratio() > 0.85):
        return by_norm[close[0]]
    candidates = sorted(set(starts + contains + [by_norm[c] for c in close]))
    if candidates:
        raise MacError(f"Не поняла, какое приложение: {', '.join(candidates[:5])}")
    raise MacError(f"Приложение {name!r} не установлено")


def open_app(name: str) -> str:
    app = resolve_app(name)
    run(["open", "-a", app])
    return app


def quit_app(name: str) -> str:
    running = running_apps()
    app = resolve_app(name, {n: Path(n) for n in running}) if running else name
    # обычный quit: приложение само спросит про несохранённое, ничего не теряется молча
    osascript(f"tell application {quote(app)} to quit")
    return app


def running_apps() -> list[str]:
    out = osascript('tell application "System Events" to get name of (every process whose background only is false)')
    return [a.strip() for a in out.split(",") if a.strip()]


def frontmost_app() -> str:
    return osascript(
        'tell application "System Events" to get name of first application process whose frontmost is true'
    )


def open_url(url: str) -> None:
    if not re.match(r"^https?://", url):
        raise MacError("Открываю только ссылки http и https")
    run(["open", url])


# ---------- система ----------


def set_dark_mode(mode: str) -> bool:
    value = {"on": "true", "off": "false", "toggle": "not dark mode"}[mode]
    out = osascript(
        'tell application "System Events" to tell appearance preferences\n'
        f"    set dark mode to {value}\n    return dark mode as text\nend tell"
    )
    return out.strip() == "true"


def battery() -> dict | None:
    out = run(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%;\s*([^;]+);", out)
    if not m:
        return None  # стационарный мак без батареи
    return {"percent": int(m.group(1)), "state": m.group(2).strip(), "on_ac": "AC Power" in out}


def sleep_display() -> None:
    run(["pmset", "displaysleepnow"])


def lock_screen() -> None:
    osascript('tell application "System Events" to keystroke "q" using {control down, command down}')


# ---------- Быстрые команды ----------


def list_shortcuts() -> list[str]:
    return [s for s in run(["shortcuts", "list"], timeout=20).splitlines() if s.strip()]


def resolve_shortcut(name: str, available: list[str]) -> str:
    lowered = {s.lower(): s for s in available}
    if name.lower() in lowered:
        return lowered[name.lower()]
    close = difflib.get_close_matches(name.lower(), list(lowered), n=3, cutoff=0.6)
    if len(close) == 1:
        return lowered[close[0]]
    if close:
        raise MacError("Не поняла, какую команду: " + ", ".join(lowered[c] for c in close))
    raise MacError(f"Быстрой команды {name!r} нет")


def run_shortcut(name: str, input_text: str | None = None) -> str:
    shortcut = resolve_shortcut(name, list_shortcuts())
    args = ["shortcuts", "run", shortcut]
    if input_text is None:
        return run(args, timeout=60) or "ok"
    # shortcuts принимает вход только файлом
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8") as f:
        f.write(input_text)
        f.flush()
        return run([*args, "--input-path", f.name], timeout=60) or "ok"
