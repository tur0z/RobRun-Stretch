"""Finding, identifying and launching Rob-Run."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import winreg
from dataclasses import dataclass
from pathlib import Path

import psutil

from config import GAME_EXE_NAME, GAME_WINDOW_CLASS, STEAM_APP_ID
from core import win32

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GameInstance:
    pid: int
    hwnd: int | None  # None while the game is still booting (EAC splash etc.)


@dataclass(frozen=True)
class GameInstall:
    exe: Path
    via_steam: bool
    unity_version: str | None

    @property
    def folder(self) -> Path:
        return self.exe.parent


# --- locating the install ----------------------------------------------------
def _steam_root() -> Path | None:
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                p = Path(winreg.QueryValueEx(k, value)[0])
                if p.exists():
                    return p
        except OSError:
            continue
    return None


def _steam_libraries(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for m in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(m.group(1).replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)
    return libs


def find_steam_install() -> Path | None:
    root = _steam_root()
    if not root:
        return None
    for lib in _steam_libraries(root):
        manifest = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'"installdir"\s+"([^"]+)"', text)
        if m:
            exe = lib / "steamapps" / "common" / m.group(1) / GAME_EXE_NAME
            if exe.exists():
                return exe
    return None


def unity_version(game_folder: Path, exe_name: str) -> str | None:
    ggm = game_folder / f"{Path(exe_name).stem}_Data" / "globalgamemanagers"
    try:
        with open(ggm, "rb") as f:
            head = f.read(256)
    except OSError:
        return None
    m = re.search(rb"\d{4}\.\d+\.\d+[abfpx]\d+", head)
    return m.group(0).decode() if m else None


def resolve_install(configured_exe: str) -> GameInstall | None:
    steam_exe = find_steam_install()
    exe = Path(configured_exe) if configured_exe else None
    if not exe or not exe.exists():
        exe = steam_exe
    if not exe:
        return None
    via_steam = steam_exe is not None and steam_exe.resolve() == exe.resolve()
    return GameInstall(exe=exe, via_steam=via_steam, unity_version=unity_version(exe.parent, exe.name))


# --- running instance ----------------------------------------------------------
def find_game(exe_name: str = GAME_EXE_NAME) -> GameInstance | None:
    """Locate the running game. Name match is used because EAC blocks reading
    the process image path."""
    target = exe_name.lower()
    pids = set()
    for p in psutil.process_iter(["name"]):
        name = p.info.get("name") or ""
        if name.lower() == target:
            pids.add(p.pid)
    if not pids:
        return None
    windows = win32.windows_of_pids(pids, GAME_WINDOW_CLASS)
    if windows:
        hwnd = windows[0]
        return GameInstance(pid=win32.window_pid(hwnd), hwnd=hwnd)
    return GameInstance(pid=min(pids), hwnd=None)


def is_running(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


# --- launching -------------------------------------------------------------------
def launch(install: GameInstall) -> str:
    """Start the game the way the user normally would. Returns a description."""
    if install.via_steam:
        os.startfile(f"steam://rungameid/{STEAM_APP_ID}")
        return "Launched through Steam"
    protected = install.folder / "start_protected_game.exe"
    if protected.exists():
        # The EasyAntiCheat bootstrapper; launching ROB RUN.exe directly
        # would start the game without anti-cheat and online play would fail.
        subprocess.Popen([str(protected)], cwd=str(install.folder))
        return "Launched through EasyAntiCheat bootstrapper"
    subprocess.Popen([str(install.exe)], cwd=str(install.folder))
    return f"Launched {install.exe.name}"
