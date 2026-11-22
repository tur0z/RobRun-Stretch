"""Stretched 4:3 without touching the monitor's display mode.

The game itself renders a real 1440x1080 frame into its 4:3 window (see
core.resolution_manager). This overlay is a full-monitor, click-through, topmost
window that hosts a DWM thumbnail of that window: DWM draws the game's frame
stretched to 1920x1080 in the same composition pass. Input is untouched — clicks
and keys fall through to the game window underneath.

The one thing that would break the illusion is the hardware cursor: it is drawn at
its real position, in game coordinates, while the picture is stretched. So while
the overlay is up the cursor is clipped to the game's client area, the hardware
cursor is hidden, and the current cursor image is drawn at the stretched position
(and stretched by the same factor), exactly as a stretched game would show it.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from core import compositor, win32
from core.win32 import Rect

log = logging.getLogger(__name__)

_FLAGS = (Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
          | Qt.WindowTransparentForInput | Qt.WindowStaysOnTopHint)
_PLACE = win32.SWP_NOACTIVATE | win32.SWP_NOOWNERZORDER | win32.SWP_SHOWWINDOW


class _Screen(QWidget):
    """Black, click-through surface the thumbnail is drawn into."""

    def __init__(self):
        super().__init__(None, _FLAGS)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setWindowTitle("Rob-Run stretched 4:3")

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0))


class _CursorSprite(QWidget):
    def __init__(self):
        super().__init__(None, _FLAGS)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.pixmap = QPixmap()

    def set_pixmap(self, pm: QPixmap):
        self.pixmap = pm
        self.resize(pm.size())
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.drawPixmap(0, 0, self.pixmap)


class StretchOverlay:
    def __init__(self):
        self._screen = _Screen()
        self._sprite = _CursorSprite()
        self._thumb: int | None = None
        self._thumb_game: int | None = None
        self._geometry: tuple[Rect, Rect] | None = None
        self._styled = False
        self._last_raise = 0.0
        self._cursor_hidden = False
        self._clip: Rect | None = None
        self._cursor_cache: dict[tuple[int, float], tuple[QPixmap, float, float]] = {}
        self._monitor: Rect | None = None
        self._client: Rect | None = None
        self._timer = QTimer(interval=4, timerType=Qt.PreciseTimer, timeout=self._track_cursor)

    @property
    def visible(self) -> bool:
        return self._screen.isVisible()

    # -- lifecycle -----------------------------------------------------------------------------
    def show(self, game_hwnd: int, monitor: Rect, client: Rect) -> None:
        """Idempotent; called every UI tick while the game is focused and 4:3 is on.
        Raises OSError if DWM refuses the thumbnail."""
        first = not self._screen.isVisible()
        if first:
            self._screen.show()
        hwnd = int(self._screen.winId())
        if not self._styled:
            compositor.make_click_through(hwnd)
            self._styled = True

        if self._thumb_game != game_hwnd:
            self._drop_thumbnail()
            self._thumb = compositor.register_thumbnail(hwnd, game_hwnd)
            self._thumb_game = game_hwnd
            self._geometry = None
            log.info("Stretch overlay attached to the game window")

        now = time.monotonic()
        if (monitor, client) != self._geometry:
            win32.set_window_pos(hwnd, win32.HWND_TOPMOST, monitor.left, monitor.top,
                                 monitor.width, monitor.height, _PLACE)
            compositor.update_thumbnail(self._thumb, Rect(0, 0, client.width, client.height),
                                        Rect(0, 0, monitor.width, monitor.height))
            self._geometry = (monitor, client)
            self._monitor, self._client = monitor, client
            self._last_raise = now
            log.info("Stretching %dx%d -> %dx%d", client.width, client.height, monitor.width, monitor.height)
        elif now - self._last_raise > 0.5:
            # The taskbar and other topmost windows can surface over us; stay on top.
            win32.set_z_order(hwnd, win32.HWND_TOPMOST)
            if self._sprite.isVisible():
                win32.set_z_order(int(self._sprite.winId()), win32.HWND_TOPMOST)
            self._last_raise = now

        if first:
            self._timer.start()
            self._track_cursor()

    def hide(self) -> None:
        if not self._screen.isVisible():
            return
        self._timer.stop()
        self._sprite.hide()
        self._screen.hide()
        self._restore_cursor()

    def release(self) -> None:
        self.hide()
        self._drop_thumbnail()
        compositor.release_magnification()

    def _drop_thumbnail(self):
        if self._thumb:
            compositor.unregister_thumbnail(self._thumb)
        self._thumb = self._thumb_game = None

    # -- cursor ----------------------------------------------------------------------------------
    def _restore_cursor(self):
        if self._clip is not None:
            if compositor.current_clip() == self._clip:
                compositor.clip_cursor(None)
            self._clip = None
        if self._cursor_hidden:
            compositor.show_system_cursor(True)
            self._cursor_hidden = False

    def _track_cursor(self):
        mon, cl = self._monitor, self._client
        if not mon or not cl:
            return
        visible, hcursor, (x, y) = compositor.cursor_state()
        if not visible or not hcursor:
            # The game hides the cursor while the camera is mouse-driven; Unity keeps it
            # locked itself, so nothing to draw or clip.
            if self._sprite.isVisible():
                self._sprite.hide()
            return

        if not self._cursor_hidden:
            try:
                compositor.show_system_cursor(False)
                self._cursor_hidden = True
            except OSError as e:
                log.warning("Cannot hide the system cursor: %s", e)
        if self._clip != cl or compositor.current_clip() != cl:
            compositor.clip_cursor(cl)
            self._clip = cl

        sx, sy = mon.width / cl.width, mon.height / cl.height
        entry = self._cursor_cache.get((hcursor, sx))
        if entry is None:
            entry = self._build_cursor(hcursor, sx, sy)
            if entry is None:
                return
            self._cursor_cache[(hcursor, sx)] = entry
        pm, hx, hy = entry
        if self._sprite.pixmap.cacheKey() != pm.cacheKey():
            self._sprite.set_pixmap(pm)

        dx = mon.left + (x - cl.left) * sx - hx
        dy = mon.top + (y - cl.top) * sy - hy
        sprite = int(self._sprite.winId())
        if not self._sprite.isVisible():
            self._sprite.show()
            win32.set_z_order(sprite, win32.HWND_TOPMOST)
        win32.set_window_pos(sprite, 0, round(dx), round(dy), pm.width(), pm.height(),
                             win32.SWP_NOACTIVATE | win32.SWP_NOZORDER | win32.SWP_NOOWNERZORDER)

    @staticmethod
    def _build_cursor(hcursor: int, sx: float, sy: float):
        img = compositor.cursor_image(hcursor)
        if img is None:
            return None
        data, size, (hx, hy) = img
        qimg = QImage(data, size, size, size * 4, QImage.Format_ARGB32_Premultiplied).copy()
        # Trim the empty canvas to the drawn pixels so the sprite window stays small.
        box = QRect()
        for yy in range(size):
            for xx in range(size):
                if qimg.pixelColor(xx, yy).alpha():
                    box = box.united(QRect(xx, yy, 1, 1))
        if box.isEmpty():
            return None
        box = QRect(0, 0, box.right() + 1, box.bottom() + 1)
        qimg = qimg.copy(box).scaled(round(box.width() * sx), round(box.height() * sy),
                                     Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return QPixmap.fromImage(qimg), hx * sx, hy * sy
