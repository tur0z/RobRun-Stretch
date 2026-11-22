"""Persistent settings, app constants and the Windows autostart entry."""
from __future__ import annotations

import json
import logging
import os
import sys
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Rob-Run Resolution Tool"
APP_ID = "RobRunResolutionTool"
APP_VERSION = "1.0.0"

STEAM_APP_ID = 4262460
GAME_EXE_NAME = "ROB RUN.exe"
GAME_WINDOW_CLASS = "UnityWndClass"
UNITY_PREFS_KEY = r"Software\Kefir\ROB RUN"

TARGET_WIDTH = 1440
TARGET_HEIGHT = 1080

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_ID
CONFIG_PATH = DATA_DIR / "settings.json"
LOG_PATH = DATA_DIR / "app.log"

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

log = logging.getLogger(__name__)


@dataclass
class Settings:
    game_exe: str = ""
    launch_with_windows: bool = False
    minimize_to_tray: bool = True
    auto_apply_on_launch: bool = False
    stretch_mode: bool = False
    tray_hint_shown: bool = False
    # Snapshot of the game's Unity "Screenmanager" registry prefs, kept while a
    # 4:3 session may still leave traces; restored once the game has exited.
    prefs_snapshot: dict | None = field(default=None)


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.settings = self._load()

    def _load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
            return Settings(**known)
        except FileNotFoundError:
            return Settings()
        except (OSError, ValueError, TypeError) as e:
            log.warning("Settings file unreadable (%s), using defaults", e)
            return Settings()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.settings), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def update(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.settings, k, v)
        self.save()


def autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    main = Path(__file__).resolve().parent / "main.py"
    return f'"{interpreter}" "{main}" --minimized'


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except FileNotFoundError:
        return False
