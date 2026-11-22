"""Snapshot/restore of the game's Unity screen prefs in the registry.

Unity writes "Screenmanager *" values (window size, fullscreen mode) as soon as
the game window changes mode. Without restoring them the game would boot in
windowed 1440x1080 next time, so a snapshot is taken before switching and put
back once the game has exited.
"""
from __future__ import annotations

import base64
import logging
import winreg

from config import UNITY_PREFS_KEY

log = logging.getLogger(__name__)

_PREFIX = "Screenmanager"


def snapshot() -> dict:
    values: dict[str, list] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNITY_PREFS_KEY) as key:
            i = 0
            while True:
                try:
                    name, data, kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if name.startswith(_PREFIX):
                    if isinstance(data, bytes):
                        data = "b64:" + base64.b64encode(data).decode()
                    values[name] = [data, kind]
    except FileNotFoundError:
        pass
    return values


def restore(saved: dict) -> int:
    """Put the saved values back and drop Screenmanager values that appeared since.
    Returns the number of values changed."""
    current = snapshot()
    changed = 0
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNITY_PREFS_KEY, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except OSError as e:
        log.error("Cannot open game prefs key: %s", e)
        return 0
    with key:
        for name, (data, kind) in saved.items():
            if current.get(name) == [data, kind]:
                continue
            raw = base64.b64decode(data[4:]) if isinstance(data, str) and data.startswith("b64:") else data
            winreg.SetValueEx(key, name, 0, kind, raw)
            changed += 1
        for name in current.keys() - saved.keys():
            winreg.DeleteValue(key, name)
            changed += 1
    return changed
