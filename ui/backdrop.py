"""Black full-monitor window placed directly beneath the 4:3 game window."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from core import win32
from core.win32 import Rect


class Backdrop(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setWindowTitle("Rob-Run 4:3 backdrop")
        self._styled = False

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0))

    def show_under(self, monitor: Rect, game_hwnd: int) -> None:
        if not self.isVisible():
            self.show()
        hwnd = int(self.winId())
        if not self._styled:
            win32.set_exstyle(hwnd, win32.get_exstyle(hwnd) | win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW)
            self._styled = True
        # Inserting after a topmost window makes this one topmost too, right below the game.
        win32.set_window_pos(hwnd, game_hwnd, monitor.left, monitor.top, monitor.width, monitor.height,
                             win32.SWP_NOACTIVATE | win32.SWP_NOOWNERZORDER | win32.SWP_SHOWWINDOW)

    def conceal(self) -> None:
        if self.isVisible():
            self.hide()
