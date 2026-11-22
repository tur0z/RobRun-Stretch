"""Glue between the Qt UI and the Qt-free core.

Threads:
  * GUI thread  — UI, 10 Hz ResolutionManager.tick(), backdrop.
  * watcher     — QThread polling for the game process once a second.
  * thread pool — blocking enable()/disable() calls (~1 s each).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, Signal, Slot

import config
from config import ConfigStore, TARGET_HEIGHT, TARGET_WIDTH
from core import game_prefs, process_manager, win32
from core.process_manager import GameInstall, GameInstance
from core.resolution_manager import ApplyError, ResolutionManager, classify
from ui.backdrop import Backdrop
from ui.stretch_overlay import StretchOverlay

log = logging.getLogger(__name__)

LAUNCH_TIMEOUT_S = 240
READY_SETTLE_S = 4.0      # window must exist this long, unchanged, before we touch it


class Phase(Enum):
    IDLE = "idle"
    LAUNCHING = "launching"   # waiting for the game to boot, will apply when ready
    APPLYING = "applying"
    ACTIVE = "active"
    RESTORING = "restoring"


@dataclass
class Snapshot:
    phase: Phase
    running: bool
    booting: bool
    desktop: str
    game_res: str
    game_mode: str
    game_aspect: str
    four_three: bool
    stretched: bool
    message: str
    message_kind: str          # info | ok | warn | error
    compat: str
    install_path: str


def _aspect_name(w: int, h: int) -> str:
    if not w or not h:
        return "—"
    ratio = w / h
    for name, value in (("16:9", 16 / 9), ("16:10", 16 / 10), ("4:3", 4 / 3), ("5:4", 5 / 4),
                        ("21:9", 64 / 27), ("32:9", 32 / 9)):
        if abs(ratio - value) < 0.02:
            return name
    return f"{ratio:.2f}:1"


class _TaskSignals(QObject):
    done = Signal(str, object)   # op, error message or None


class _Task(QRunnable):
    def __init__(self, op: str, fn):
        super().__init__()
        self.op, self.fn = op, fn
        self.signals = _TaskSignals()

    def run(self):
        try:
            self.fn()
            self.signals.done.emit(self.op, None)
        except ApplyError as e:
            self.signals.done.emit(self.op, str(e))
        except Exception:  # noqa: BLE001 - surface anything to the user, keep the app alive
            log.exception("%s failed", self.op)
            self.signals.done.emit(self.op, "Что-то пошло не так. Попробуйте ещё раз.")


class GameWatcher(QObject):
    changed = Signal(object)    # GameInstance | None

    def __init__(self, exe_name: str):
        super().__init__()
        self.exe_name = exe_name
        self._last: GameInstance | None = None
        self._timer: QTimer | None = None

    @Slot()
    def start(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)
        self._timer.start(1000)
        self.poll()

    @Slot()
    def poll(self):
        try:
            current = process_manager.find_game(self.exe_name)
        except Exception:  # noqa: BLE001
            log.exception("Process scan failed")
            return
        if current != self._last:
            self._last = current
            self.changed.emit(current)

    @Slot(str)
    def set_exe_name(self, name: str):
        self.exe_name = name
        self.poll()


class Controller(QObject):
    state_changed = Signal(object)          # Snapshot
    notify = Signal(str, str, str)          # title, text, kind
    _watch_exe = Signal(str)

    def __init__(self, store: ConfigStore):
        super().__init__()
        self.store = store
        self.cfg = store.settings
        self.manager = ResolutionManager(TARGET_WIDTH, TARGET_HEIGHT)
        self.manager.game_topmost = not self.cfg.stretch_mode
        self.backdrop = Backdrop()
        self.overlay = StretchOverlay()
        self._overlay_failed = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self.install: GameInstall | None = process_manager.resolve_install(self.cfg.game_exe)
        self.game: GameInstance | None = None
        self.phase = Phase.IDLE
        self.message, self.message_kind = "", "info"
        self.stretched = False
        self._game_seen_at = 0.0
        self._game_rect_stable_since = 0.0
        self._last_rect = None
        self._pending_apply = False
        self._launch_started = 0.0
        self._auto_applied_hwnd = None
        self._tasks: set[_Task] = set()

        if self.install:
            log.info("Game install: %s (%s, Unity %s)", self.install.exe,
                     "Steam" if self.install.via_steam else "manual", self.install.unity_version)
        else:
            log.warning("Rob-Run install not found; choose ROB RUN.exe in Settings")

        self._thread = QThread(self)
        self._watcher = GameWatcher(self._exe_name())
        self._watcher.moveToThread(self._thread)
        self._thread.started.connect(self._watcher.start)
        self._watcher.changed.connect(self._on_game_changed)
        self._watch_exe.connect(self._watcher.set_exe_name)
        self._thread.start()

        self._tick_timer = QTimer(self, interval=100, timeout=self._tick)
        self._tick_timer.start()
        self._ui_timer = QTimer(self, interval=500, timeout=self._refresh)
        self._ui_timer.start()

    # -- helpers ------------------------------------------------------------------
    def _exe_name(self) -> str:
        return self.install.exe.name if self.install else config.GAME_EXE_NAME

    def _set_message(self, text: str, kind: str = "info"):
        self.message, self.message_kind = text, kind
        if text:
            (log.error if kind == "error" else log.warning if kind == "warn" else log.info)(text)
        self._refresh()

    def _run(self, op: str, fn):
        task = _Task(op, fn)
        task.setAutoDelete(False)
        task.signals.done.connect(self._on_task_done)
        self._tasks.add(task)
        self.pool.start(task)

    def _game_ready(self) -> bool:
        g = self.game
        return bool(g and g.hwnd and win32.is_window(g.hwnd)
                    and time.monotonic() - self._game_rect_stable_since >= READY_SETTLE_S)

    # -- user actions -----------------------------------------------------------------
    @Slot()
    def toggle(self):
        if self.phase == Phase.ACTIVE:
            self.disable()
        elif self.phase == Phase.LAUNCHING:
            self._pending_apply = False
            self.phase = Phase.IDLE
            self._set_message("Ожидание игры отменено.")
        elif self.phase == Phase.IDLE:
            self.enable()

    def enable(self):
        g = self.game
        if g and g.hwnd and win32.is_window(g.hwnd):
            self._start_enable(g.hwnd)
            return
        self._pending_apply = True
        self.phase = Phase.LAUNCHING
        self._launch_started = time.monotonic()
        if g:
            self._set_message("Rob-Run запускается — 4:3 включится, как только игра откроется…")
            return
        if not self.install:
            self.phase = Phase.IDLE
            self._pending_apply = False
            self._set_message("Не удалось найти Rob-Run. Запустите игру сами или укажите её "
                              "в настройках.", "warn")
            return
        try:
            how = process_manager.launch(self.install)
        except OSError as e:
            self.phase = Phase.IDLE
            self._pending_apply = False
            log.error("Launch failed: %s", e)
            self._set_message("Не получилось запустить Rob-Run. Попробуйте запустить игру через Steam.",
                              "error")
            return
        log.info("%s", how)
        self._set_message("Запускаем Rob-Run — 4:3 включится, как только игра откроется…")

    def _start_enable(self, hwnd: int):
        if self.cfg.prefs_snapshot is None:
            self.store.update(prefs_snapshot=game_prefs.snapshot())
            log.info("Saved the game's screen prefs for restoring after exit")
        self.phase = Phase.APPLYING
        self._pending_apply = False
        self._set_message("Включаем 4:3…")
        self._run("enable", lambda: self.manager.enable(hwnd))

    def disable(self):
        if self.phase != Phase.ACTIVE:
            return
        self.phase = Phase.RESTORING
        self._hide_visuals()
        self._set_message("Возвращаем обычный режим…")
        self._run("disable", self.manager.disable)

    @Slot(str, object)
    def _on_task_done(self, op: str, error):
        self._tasks = {t for t in self._tasks if t.signals is not self.sender()}
        if op == "enable":
            if error:
                self.phase = Phase.IDLE
                self._set_message(error, "error")
                self.notify.emit("Не удалось включить 4:3", error, "error")
            else:
                self.phase = Phase.ACTIVE
                self._set_message("Готово! Rob-Run работает в 4:3.", "ok")
                self.notify.emit("4:3 включён", "Rob-Run работает в 4:3. Рабочий стол не изменился.", "ok")
        elif op == "disable":
            self.phase = Phase.IDLE
            if error:
                self._set_message(error, "warn")
                self.notify.emit("Не всё удалось вернуть", error, "warn")
            else:
                self._set_message("Rob-Run снова в обычном режиме.", "ok")
                self.notify.emit("4:3 выключен", "Rob-Run снова в обычном режиме.", "info")
        self._refresh()

    # -- settings -----------------------------------------------------------------------
    def set_game_exe(self, path: str):
        install = process_manager.resolve_install(path)  # empty path = Steam auto-detect
        self.install = install
        self.store.update(game_exe=path)
        self._watch_exe.emit(self._exe_name())
        log.info("Game executable set to %s", install.exe if install else "(none)")
        self._refresh()

    def auto_detect(self) -> bool:
        exe = process_manager.find_steam_install()
        if exe:
            self.set_game_exe("")
        return exe is not None

    def set_stretch(self, on: bool):
        self.store.update(stretch_mode=on)
        self.manager.game_topmost = not on
        self._overlay_failed = False
        if not on:
            self.overlay.hide()
        log.info("Stretched 4:3 %s", "enabled" if on else "disabled")

    def _hide_visuals(self):
        self.overlay.hide()
        self.backdrop.conceal()
        self.stretched = False

    # -- game process events -----------------------------------------------------------------
    @Slot(object)
    def _on_game_changed(self, game: GameInstance | None):
        prev = self.game
        self.game = game
        if game and (not prev or prev.hwnd != game.hwnd) and game.hwnd:
            self._game_seen_at = time.monotonic()
            self._game_rect_stable_since = time.monotonic()
            self._last_rect = None
            log.info("Rob-Run window found (pid %d, %s)", game.pid, classify(game.hwnd).value)
        elif game and not prev:
            log.info("Rob-Run process started (pid %d), waiting for its window", game.pid)
        if not game and prev:
            log.info("Rob-Run exited")
            self._hide_visuals()
            if self.phase in (Phase.ACTIVE, Phase.APPLYING, Phase.RESTORING):
                self.phase = Phase.IDLE
            if self.manager.active:
                self.manager.session = None
            self._restore_prefs_if_needed()
            if prev and self.message_kind != "error":
                self._set_message("Игра закрыта — всё вернули как было.", "ok")
        self._refresh()

    def _restore_prefs_if_needed(self):
        snap = self.cfg.prefs_snapshot
        if snap is None:
            return
        if self.game:  # Unity rewrites prefs on exit; only restore once it has quit
            return
        try:
            n = game_prefs.restore(snap)
            log.info("Restored the game's screen prefs (%d values changed)", n)
            self.store.update(prefs_snapshot=None)
        except OSError as e:
            log.error("Could not restore game prefs: %s", e)

    def startup_recovery(self):
        """Run once at launch: finish a restore a previous run could not complete."""
        if self.cfg.prefs_snapshot is not None and not process_manager.find_game(self._exe_name()):
            log.info("Found a pending prefs restore from a previous session")
            self._restore_prefs_if_needed()

    # -- periodic -------------------------------------------------------------------------------
    @Slot()
    def _tick(self):
        g = self.game
        if g and g.hwnd and win32.is_window(g.hwnd):
            rect = win32.window_rect(g.hwnd)
            if rect != self._last_rect:
                self._last_rect = rect
                self._game_rect_stable_since = time.monotonic()

        if self.phase == Phase.LAUNCHING and self._pending_apply:
            if self._game_ready():
                self._start_enable(self.game.hwnd)
            elif time.monotonic() - self._launch_started > LAUNCH_TIMEOUT_S:
                self.phase = Phase.IDLE
                self._pending_apply = False
                self._set_message("Rob-Run так и не открылась. Запустите игру и нажмите кнопку ещё раз.",
                                  "error")
        elif (self.phase == Phase.IDLE and self.cfg.auto_apply_on_launch and g and g.hwnd
              and g.hwnd != self._auto_applied_hwnd and self._game_ready()):
            self._auto_applied_hwnd = g.hwnd
            log.info("Auto-applying 4:3 to the new game window")
            self._start_enable(g.hwnd)

        if self.phase != Phase.ACTIVE:
            return
        try:
            res = self.manager.tick()
        except ApplyError as e:
            log.error("Tick: %s", e)
            return
        if res is None:
            return
        if res.event in ("game_closed", "game_fullscreen", "lost_control"):
            self._hide_visuals()
            self.phase = Phase.IDLE
            text = {
                "game_closed": "Игра закрыта — 4:3 выключен.",
                "game_fullscreen": "Игра сама вернулась в полноэкранный режим, поэтому 4:3 выключен.",
                "lost_control": "Игра не даёт удержать 4:3. Режим выключен — попробуйте ещё раз.",
            }[res.event]
            self._set_message(text, "warn" if res.event != "game_closed" else "info")
            self.notify.emit("4:3 выключен", text, "warn")
            return
        if not (res.game_foreground and res.monitor_rect):
            # Alt+Tab: just take the overlay down. No display mode is involved, so
            # nothing flickers, and coming back is a single window show.
            self._hide_visuals()
            return
        if self.cfg.stretch_mode and not self._overlay_failed:
            try:
                self.overlay.show(self.game.hwnd, res.monitor_rect, res.client_rect)
                self.backdrop.conceal()
                self.stretched = True
                return
            except OSError as e:
                self._overlay_failed = True
                self.overlay.hide()
                self.manager.game_topmost = True
                log.error("Stretch overlay failed: %s", e)
                self._set_message("Растянуть картинку не получилось — 4:3 показан с чёрными полосами.", "warn")
        self.stretched = False
        self.backdrop.show_under(res.monitor_rect, self.game.hwnd)

    @Slot()
    def _refresh(self):
        g = self.game
        running = bool(g)
        booting = bool(g and not g.hwnd)
        mon = win32.monitor_of_window(g.hwnd) if g and g.hwnd and win32.is_window(g.hwnd) \
            else win32.primary_monitor()
        desk = win32.desktop_display_mode(mon.device)
        desktop = f"{desk.width}×{desk.height}" if desk else "—"
        if desk and desk.frequency > 1:
            desktop += f"  @ {desk.frequency} Hz"

        game_res, game_mode, aspect, four_three = "—", "", "—", False
        if g and g.hwnd and win32.is_window(g.hwnd):
            w, h = win32.client_size(g.hwnd)
            game_res = f"{w}×{h}"
            aspect = _aspect_name(w, h)
            four_three = self.phase == Phase.ACTIVE and aspect == "4:3"
            game_mode = "4:3 window" if self.phase == Phase.ACTIVE else classify(g.hwnd).value
            if self.phase == Phase.ACTIVE and self.stretched:
                game_mode = f"4:3 stretched to {mon.rect.width}×{mon.rect.height}"

        compat = ""
        if self.install and self.install.unity_version:
            compat = f"Unity {self.install.unity_version}"
        if g and g.hwnd and win32.is_window(g.hwnd):
            ok = win32.get_class_name(g.hwnd) == config.GAME_WINDOW_CLASS
            compat = (compat + "  ·  " if compat else "") + \
                ("Live 4:3 supported" if ok else "Unknown window type")

        self.state_changed.emit(Snapshot(
            phase=self.phase, running=running, booting=booting, desktop=desktop,
            game_res=game_res, game_mode=game_mode, game_aspect=aspect, four_three=four_three,
            stretched=self.stretched, message=self.message, message_kind=self.message_kind,
            compat=compat, install_path=str(self.install.exe) if self.install else "",
        ))

    # -- shutdown -------------------------------------------------------------------------------
    def shutdown(self):
        self._tick_timer.stop()
        self._ui_timer.stop()
        self.pool.waitForDone(8000)
        if self.manager.active:
            log.info("Exiting: restoring the game before quitting")
            self.manager.shutdown()
        self.overlay.release()
        self.backdrop.conceal()
        self._thread.quit()
        self._thread.wait(3000)
