"""Логика управления маком без настоящего macOS: системные вызовы подменены."""

import subprocess
from pathlib import Path

import pytest

from friday.integrations import macos
from friday.tools import mac as mac_tools

APPS = {
    n: Path(f"/Applications/{n}.app")
    for n in ("Safari", "Telegram", "Visual Studio Code", "PyCharm CE", "PyCharm", "Music", "System Settings", "Notes")
}


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("safari", "Safari"),
        ("Telegram", "Telegram"),
        ("телеграм", None),  # русские названия модель переводит сама, тут не угадываем
        ("visual studio", "Visual Studio Code"),
        ("vs code", "Visual Studio Code"),
        ("VSC", "Visual Studio Code"),
        ("pycharm", "PyCharm"),
        ("Pycharm CE", "PyCharm CE"),
        ("settings", "System Settings"),
        ("Telegarm", "Telegram"),  # опечатка
    ],
)
def test_resolve_app(asked, expected):
    if expected is None:
        with pytest.raises(macos.MacError):
            macos.resolve_app(asked, APPS)
    else:
        assert macos.resolve_app(asked, APPS) == expected


def test_resolve_app_ambiguous_lists_candidates():
    apps = {n: Path(n) for n in ("Microsoft Word", "Microsoft Excel")}
    with pytest.raises(macos.MacError, match="Microsoft Excel, Microsoft Word"):
        macos.resolve_app("microsoft", apps)


def test_quote_escapes():
    assert macos.quote('a "b" \\ c') == '"a \\"b\\" \\\\ c"'


class _Fn:
    """Функция из C-библиотеки: можно выставлять argtypes/restype, как у ctypes."""

    def __init__(self, impl):
        self.impl = impl

    def __call__(self, *args):
        return self.impl(*args)


class FakeDisplays:
    """CoreGraphics + DisplayServices: дисплей 1 внешний, 2 встроенный."""

    def __init__(self, builtin=True, applies=True):
        self.levels = {1: -1.0, 2: 0.45}
        self.applies = applies  # False: вызов "успешен", но яркость не меняется (как key code на M-чипах)
        self.CGMainDisplayID = _Fn(lambda: 1)
        self.CGGetOnlineDisplayList = _Fn(self._list)
        self.CGDisplayIsBuiltin = _Fn(lambda d: int(builtin and d == 2))
        self.DisplayServicesGetBrightness = _Fn(self._get)
        self.DisplayServicesSetBrightness = _Fn(self._set)

    def _list(self, max_n, ids, count_ref):
        ids[0], ids[1] = 1, 2
        count_ref._obj.value = 2
        return 0

    def _get(self, display, value_ref):
        if self.levels[display] < 0:
            return 1  # внешний монитор: ошибка
        value_ref._obj.value = self.levels[display]
        return 0

    def _set(self, display, level):
        if self.levels[display] < 0:
            return 1
        if self.applies:
            self.levels[display] = level
        return 0


@pytest.fixture
def displays(monkeypatch):
    def make(**kwargs):
        fake = FakeDisplays(**kwargs)
        monkeypatch.setattr(macos, "_display", macos.DisplayBrightness(cg=fake, ds=fake))
        return fake

    return make


def test_brightness_targets_builtin_and_reads_back(displays):
    fake = displays()
    assert macos.get_brightness() == 45
    assert macos.set_brightness(100) == 100
    assert fake.levels[2] == pytest.approx(1.0)
    assert fake.levels[1] == -1.0  # внешний не трогали


def test_brightness_clamped_and_relative(displays):
    displays()
    assert macos.set_brightness(150) == 100
    assert macos.change_brightness(-30) == 70


def test_brightness_not_applied_is_reported(displays):
    displays(applies=False)
    with pytest.raises(macos.MacError, match="сейчас 45%"):
        macos.set_brightness(100)


def test_brightness_external_only(displays):
    displays(builtin=False)
    with pytest.raises(macos.MacError, match="внешний монитор"):
        macos.get_brightness()


def test_brightness_tool_reports_actual_value(displays):
    displays()
    assert mac_tools.set_brightness(level=80) == {"brightness_pct": 80}
    assert mac_tools.get_brightness() == {"brightness_pct": 80}


def test_open_url_only_http():
    with pytest.raises(macos.MacError):
        macos.open_url("file:///etc/passwd")


def test_resolve_shortcut():
    available = ["Не беспокоить", "Режим кино", "Спокойной ночи"]
    assert macos.resolve_shortcut("режим кино", available) == "Режим кино"
    assert macos.resolve_shortcut("спокойной ночь", available) == "Спокойной ночи"
    with pytest.raises(macos.MacError):
        macos.resolve_shortcut("вызвать такси", available)


# ---------- разбор ответов системных утилит ----------


def _fake_run(monkeypatch, stdout="", returncode=0, stderr=""):
    calls = []

    def fake(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(macos.subprocess, "run", fake)
    return calls


def test_get_volume_parsing(monkeypatch):
    _fake_run(monkeypatch, stdout="35,false\n")
    assert macos.get_volume() == {"level": 35, "muted": False}


def test_battery_parsing(monkeypatch):
    out = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t76%; discharging; 4:12 remaining present: true"
    _fake_run(monkeypatch, stdout=out)
    assert macos.battery() == {"percent": 76, "state": "discharging", "on_ac": False}


def test_battery_absent_on_desktop(monkeypatch):
    _fake_run(monkeypatch, stdout="Now drawing from 'AC Power'\n")
    assert macos.battery() is None


@pytest.mark.parametrize(
    ("stderr", "hint"),
    [
        (
            "execution error: System Events got an error: osascript is not allowed assistive access. (-1719)",
            "Универсальный доступ",
        ),
        ("execution error: Not authorized to send Apple events to System Events. (-1743)", "Автоматизация"),
    ],
)
def test_permission_errors_are_explained(monkeypatch, stderr, hint):
    _fake_run(monkeypatch, returncode=1, stderr=stderr)
    with pytest.raises(macos.MacError, match=hint):
        macos.osascript("whatever")


def test_osascript_passes_script_via_stdin(monkeypatch):
    calls = _fake_run(monkeypatch)
    macos.set_volume(130)
    args, script = calls[0]
    assert args == ["osascript", "-"]
    assert "set volume output volume 100" in script  # обрезано до 100


def test_running_apps_parsing(monkeypatch):
    _fake_run(monkeypatch, stdout="Finder, Safari, Telegram\n")
    assert macos.running_apps() == ["Finder", "Safari", "Telegram"]


# ---------- инструменты ----------


def test_volume_change_relative(monkeypatch):
    state = {"level": 40, "muted": False}
    monkeypatch.setattr(macos, "get_volume", lambda: dict(state))
    monkeypatch.setattr(macos, "set_volume", lambda v: state.update(level=max(0, min(100, v))))
    monkeypatch.setattr(macos, "set_muted", lambda m: state.update(muted=m))

    assert mac_tools.set_volume(change=10)["level"] == 50
    assert mac_tools.set_volume(change=-80)["level"] == 0
    assert mac_tools.set_volume(mute=True)["muted"] is True


def test_brightness_requires_argument():
    with pytest.raises(ValueError):
        mac_tools.set_brightness()


def test_mac_tools_registered_only_on_mac():
    from friday.tools import load_all

    names = {t.name for t in load_all().all()}
    assert ("set_volume" in names) is macos.IS_MAC
