"""Switching Rob-Run between its normal mode and a true 1440x1080 4:3 window.

How it works (verified against ROB RUN, Unity 6000.3, D3D12):

1. Unity's borderless fullscreen ("FullScreenWindow") pins its window to the
   monitor and snaps back any external resize, so the game is first taken out of
   fullscreen with Alt+Enter, posted straight to its message queue.
2. In windowed mode the Unity player resizes its swap chain to the window's client
   area on WM_SIZE. Stripping the frame and sizing the client area to 1440x1080
   therefore changes the actual render resolution: the camera gets a 4:3 FOV and
   the HUD re-lays itself out for 4:3. This is not a scaled 16:9 image.
3. The window is centred on its monitor; a black backdrop fills the sides and the
   window is kept above the taskbar while the game has focus.
4. Disabling reverses the steps (restore the windowed frame, Alt+Enter back to
   fullscreen) and verifies the game reports the original geometry.

The display mode of the monitor is never changed. Stretched output is done
separately by ui.stretch_overlay (a DWM thumbnail of this 4:3 window).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from core import win32
from core.win32 import Rect

log = logging.getLogger(__name__)


class ApplyError(Exception):
    """A step failed; the message is shown to the user."""


class DisplayKind(Enum):
    BORDERLESS = "Borderless fullscreen"
    EXCLUSIVE = "Exclusive fullscreen"
    WINDOWED = "Windowed"
    BORDERLESS_WINDOW = "Borderless window"


def _has_caption(style: int) -> bool:
    return style & win32.WS_CAPTION == win32.WS_CAPTION


def classify(hwnd: int) -> DisplayKind:
    style = win32.get_style(hwnd)
    if _has_caption(style):
        return DisplayKind.WINDOWED
    mon = win32.monitor_of_window(hwnd)
    if win32.window_rect(hwnd) == mon.rect:
        cur = win32.current_display_mode(mon.device)
        desk = win32.desktop_display_mode(mon.device)
        if cur and desk and (cur.width, cur.height) != (desk.width, desk.height):
            return DisplayKind.EXCLUSIVE
        return DisplayKind.BORDERLESS
    return DisplayKind.BORDERLESS_WINDOW


def fit_target(mon: Rect, width: int, height: int) -> tuple[int, int]:
    """1440x1080 when it fits, otherwise the largest 4:3 size that does."""
    if mon.width >= width and mon.height >= height:
        return width, height
    scale = min(mon.width / width, mon.height / height)
    return int(width * scale) // 4 * 4, int(height * scale) // 3 * 3


@dataclass
class Session:
    hwnd: int
    target_w: int
    target_h: int
    original_kind: DisplayKind
    original_style: int
    original_exstyle: int
    original_rect: Rect
    via_alt_enter: bool
    windowed_style: int = 0
    windowed_exstyle: int = 0
    windowed_rect: Rect | None = None
    device: str = ""
    topmost: bool = False
    last_topmost_at: float = 0.0
    fg_state: bool = False
    fg_since: float = 0.0
    reverts: deque = field(default_factory=lambda: deque(maxlen=16))


@dataclass(frozen=True)
class TickResult:
    event: str | None          # "game_closed" | "game_fullscreen" | "lost_control"
    game_foreground: bool = False
    monitor_rect: Rect | None = None
    client_rect: Rect | None = None   # the game's 4:3 client area in screen coordinates


class ResolutionManager:
    def __init__(self, target_w: int, target_h: int):
        self.target_w = target_w
        self.target_h = target_h
        # Native 4:3 keeps the focused game above the taskbar. The stretch overlay
        # takes that role instead, so it turns this off.
        self.game_topmost = True
        self.session: Session | None = None
        self._lock = threading.RLock()

    # -- public -----------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.session is not None

    def enable(self, hwnd: int) -> Session:
        """Blocking (up to a few seconds). Call from a worker thread."""
        with self._lock:
            if self.session:
                return self.session
            if not win32.is_window(hwnd):
                raise ApplyError("Окно Rob-Run не найдено.")
            win32.restore_if_minimized(hwnd)

            kind = classify(hwnd)
            style, exstyle = win32.get_style(hwnd), win32.get_exstyle(hwnd)
            rect = win32.window_rect(hwnd)
            log.info("Enable: game is %s, window %s, client %s, style 0x%08X",
                     kind.value, rect.as_tuple(), win32.client_size(hwnd), style)

            s = Session(hwnd=hwnd, target_w=0, target_h=0, original_kind=kind,
                        original_style=style, original_exstyle=exstyle, original_rect=rect,
                        via_alt_enter=False)

            if kind in (DisplayKind.BORDERLESS, DisplayKind.EXCLUSIVE):
                log.info("Leaving Unity fullscreen with Alt+Enter")
                win32.post_alt_enter(hwnd)
                if not self._wait(lambda: _has_caption(win32.get_style(hwnd)), 5.0):
                    raise ApplyError("Игра не вышла из полноэкранного режима. Выберите в настройках "
                                     "Rob-Run оконный режим и нажмите кнопку ещё раз.")
                s.via_alt_enter = True
                time.sleep(0.3)  # let the player finish recreating its swap chain
                s.windowed_style = win32.get_style(hwnd)
                s.windowed_exstyle = win32.get_exstyle(hwnd)
                s.windowed_rect = win32.window_rect(hwnd)
                log.info("Game is windowed: %s", s.windowed_rect.as_tuple())

            mon = win32.monitor_of_window(hwnd)
            s.device = mon.device
            s.target_w, s.target_h = fit_target(mon.rect, self.target_w, self.target_h)
            if (s.target_w, s.target_h) != (self.target_w, self.target_h):
                log.warning("Monitor %dx%d is smaller than %dx%d, using %dx%d (still 4:3)",
                            mon.rect.width, mon.rect.height, self.target_w, self.target_h,
                            s.target_w, s.target_h)
            self.session = s

            try:
                for attempt in range(1, 4):
                    self._place(s)
                    if self._wait(lambda: self._in_place(s), 2.0, stable_checks=3):
                        break
                    log.warning("Placement attempt %d not confirmed: window %s, client %s",
                                attempt, win32.window_rect(hwnd).as_tuple(), win32.client_size(hwnd))
                else:
                    raise ApplyError("Игра не даёт включить 4:3. Попробуйте ещё раз.")
            except Exception:
                self._restore(s)
                self.session = None
                raise

            log.info("4:3 active: client %s at %s", win32.client_size(hwnd),
                     win32.window_rect(hwnd).as_tuple())
            return s

    def disable(self) -> None:
        """Blocking. Restores the game window to the mode it had before enable()."""
        with self._lock:
            s = self.session
            if not s:
                return
            self.session = None
            self._restore(s)

    def tick(self) -> TickResult | None:
        """Cheap periodic check (~10 Hz) from the UI thread: keeps the 4:3 window in
        place, manages z-order, and reports game exit or takeover."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            s = self.session
            if not s:
                return None
            now = time.monotonic()
            hwnd = s.hwnd
            if not win32.is_window(hwnd):
                self.session = None
                return TickResult("game_closed")

            fg = win32.foreground_window()
            game_fg = fg == hwnd
            if game_fg != s.fg_state:
                s.fg_state, s.fg_since = game_fg, now

            mon = win32.monitor_of_window(hwnd)
            style = win32.get_style(hwnd)
            rect = win32.window_rect(hwnd)
            unity_fullscreen = (not _has_caption(style) and rect == mon.rect
                                and (mon.rect.width, mon.rect.height) != (s.target_w, s.target_h))
            if unity_fullscreen:
                # The player went back to fullscreen on its own (Alt+Enter by the
                # user or an in-game display setting). Respect that, don't fight it.
                log.info("Game returned to fullscreen by itself; 4:3 session ended")
                self._drop_topmost(s, fg)
                self.session = None
                return TickResult("game_fullscreen")

            if not win32.is_minimized(hwnd) and not self._in_place(s):
                s.reverts.append(now)
                recent = [t for t in s.reverts if now - t < 10]
                if len(recent) >= 6:
                    log.error("Game keeps overriding the window size; giving up")
                    self._drop_topmost(s, fg)
                    self.session = None
                    return TickResult("lost_control")
                log.info("Window drifted to %s / client %s, re-applying",
                         rect.as_tuple(), win32.client_size(hwnd))
                self._place(s)

            if game_fg and self.game_topmost:
                if not s.topmost or now - s.last_topmost_at > 1.0:
                    win32.set_z_order(hwnd, win32.HWND_TOPMOST)
                    s.topmost, s.last_topmost_at = True, now
            elif s.topmost:
                self._drop_topmost(s, fg)

            return TickResult(None, game_fg, mon.rect, self._expected_rect(s))
        finally:
            self._lock.release()

    def shutdown(self) -> None:
        try:
            self.disable()
        except ApplyError as e:
            log.warning("Restore on exit incomplete: %s", e)

    # -- internals ----------------------------------------------------------------
    @staticmethod
    def _wait(predicate, timeout: float, stable_checks: int = 1, interval: float = 0.1) -> bool:
        deadline = time.monotonic() + timeout
        streak = 0
        while time.monotonic() < deadline:
            if predicate():
                streak += 1
                if streak >= stable_checks:
                    return True
            else:
                streak = 0
            time.sleep(interval)
        return False

    @staticmethod
    def _expected_rect(s: Session) -> Rect:
        mon = win32.monitor_of_window(s.hwnd).rect
        x = mon.left + (mon.width - s.target_w) // 2
        y = mon.top + (mon.height - s.target_h) // 2
        return Rect(x, y, x + s.target_w, y + s.target_h)

    def _in_place(self, s: Session) -> bool:
        return (not _has_caption(win32.get_style(s.hwnd))
                and win32.client_size(s.hwnd) == (s.target_w, s.target_h)
                and win32.window_rect(s.hwnd) == self._expected_rect(s))

    def _place(self, s: Session) -> None:
        style = win32.get_style(s.hwnd)
        exstyle = win32.get_exstyle(s.hwnd)
        win32.set_style(s.hwnd, (style & ~win32.FRAME_STYLES) | win32.WS_POPUP | win32.WS_VISIBLE)
        win32.set_exstyle(s.hwnd, exstyle & ~win32.FRAME_EXSTYLES)
        r = self._expected_rect(s)
        ok = win32.set_window_pos(s.hwnd, win32.HWND_TOP, r.left, r.top, r.width, r.height,
                                  win32.SWP_FRAMECHANGED | win32.SWP_NOACTIVATE
                                  | win32.SWP_SHOWWINDOW | win32.SWP_NOOWNERZORDER)
        if not ok:
            log.error("SetWindowPos failed, error %d", win32.last_error())
            raise ApplyError("Windows не дала изменить окно игры. Попробуйте ещё раз.")

    def _restore(self, s: Session) -> None:
        hwnd = s.hwnd
        if not win32.is_window(hwnd):
            return
        self._drop_topmost(s, 0)
        flags = (win32.SWP_FRAMECHANGED | win32.SWP_NOACTIVATE
                 | win32.SWP_NOZORDER | win32.SWP_NOOWNERZORDER)
        if s.via_alt_enter:
            # Put the windowed frame back first so the switch to fullscreen is observable.
            r = s.windowed_rect
            win32.set_style(hwnd, s.windowed_style)
            win32.set_exstyle(hwnd, s.windowed_exstyle)
            win32.set_window_pos(hwnd, 0, r.left, r.top, r.width, r.height, flags)
            time.sleep(0.3)
            log.info("Returning game to %s with Alt+Enter", s.original_kind.value)
            win32.post_alt_enter(hwnd)
            mon = win32.monitor_of_window(hwnd).rect
            back = self._wait(lambda: not _has_caption(win32.get_style(hwnd))
                              and win32.window_rect(hwnd) == win32.monitor_of_window(hwnd).rect,
                              5.0, stable_checks=3)
            if not back:
                raise ApplyError("Игра не вернулась в полный экран. Нажмите в игре Alt+Enter.")
            log.info("Game restored: %s, client %s", mon.as_tuple(), win32.client_size(hwnd))
        else:
            r = s.original_rect
            win32.set_style(hwnd, s.original_style)
            win32.set_exstyle(hwnd, s.original_exstyle)
            win32.set_window_pos(hwnd, 0, r.left, r.top, r.width, r.height, flags)
            if not self._wait(lambda: win32.window_rect(hwnd) == r, 2.0, stable_checks=2):
                raise ApplyError("Окно игры не вернулось к прежнему размеру.")
            log.info("Game window restored to %s", r.as_tuple())

    @staticmethod
    def _drop_topmost(s: Session, fg: int) -> None:
        if not s.topmost or not win32.is_window(s.hwnd):
            s.topmost = False
            return
        win32.set_z_order(s.hwnd, win32.HWND_NOTOPMOST)
        # HWND_NOTOPMOST lifts the window above all normal windows; tuck it
        # back under the app the user switched to.
        if fg and fg != s.hwnd and not (win32.get_exstyle(fg) & win32.WS_EX_TOPMOST):
            win32.set_z_order(s.hwnd, fg)
        s.topmost = False
