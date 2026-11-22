"""Main window (horizontal, user-facing), settings panel, developer window, tray."""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation, QRectF, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QAction, QColor, QGuiApplication, QKeySequence, QLinearGradient, QPainter,
                           QPen, QPixmap, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMenu, QPlainTextEdit, QPushButton, QSystemTrayIcon, QVBoxLayout,
                               QWidget)

import config
from config import APP_VERSION, LOG_PATH
from core import win32
from ui import theme
from ui.controller import Controller, Phase, Snapshot
from ui.widgets import StatusDot, Switch, ToggleButton, _lerp, _mix, app_icon, asset
from ui.theme import qc

log = logging.getLogger(__name__)

WINDOW_TITLE = "Rob-Run 4:3"
WIN_W, WIN_H = 1200, 660
ICON_MIN, ICON_CLOSE, ICON_SETTINGS = "\uE921", "\uE8BB", "\uE713"


LOCAL_QSS = f"""
#Glass {{
    background: rgba(12, 12, 15, 0.70);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 16px;
}}
#Panel {{
    background: rgba(10, 10, 13, 0.94);
    border-left: 1px solid rgba(255, 122, 26, 0.28);
}}
QLabel[role="sub"] {{ color: #A9AFBC; font-size: 15px; }}
QLabel[role="cap"] {{
    color: {theme.MUTED}; font-family: "{theme.HEADING_FAMILY}"; font-size: 12px; letter-spacing: 2px;
}}
QLabel[role="big"] {{ color: {theme.TEXT}; font-size: 17px; font-weight: 600; }}
QLabel[role="optTitle"] {{ color: {theme.TEXT}; font-size: 14px; font-weight: 600; }}
QLabel[role="optDesc"] {{ color: {theme.MUTED}; font-size: 12px; }}
QLabel[role="tiny"] {{ color: {theme.FAINT}; font-size: 11px; }}
QPushButton[kind="soft"] {{
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 10px;
    padding: 9px 16px;
    color: #C9CDD6;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton[kind="soft"]:hover {{
    border-color: {theme.ACCENT}; color: {theme.TEXT}; background: rgba(255, 122, 26, 0.10);
}}
QPushButton[kind="soft"]:pressed {{ background: rgba(255, 122, 26, 0.18); }}
"""


# --- logging bridge (developer mode only) ---------------------------------------------------
class QtLogBridge(QObject):
    """Forwards log records to the developer window; Qt queues the signal across threads."""
    line = Signal(str)

    def __init__(self):
        super().__init__()
        self.handler = _BridgeHandler(self)
        self.handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))


class _BridgeHandler(logging.Handler):
    def __init__(self, bridge: QtLogBridge):
        super().__init__()
        self.bridge = bridge

    def emit(self, record):
        try:
            self.bridge.line.emit(self.format(record))
        except RuntimeError:  # bridge already destroyed during shutdown
            pass


def _label(text: str = "", role: str | None = None) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    return lab


def _button(text: str, kind: str, slot) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("kind", kind)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(slot)
    return b


def _inset(item, px: int = 14) -> QHBoxLayout:
    """Wrap a widget/layout with side margins matching ToggleButton's glow padding,
    so every block in the column shares the button's visible edges."""
    row = QHBoxLayout()
    row.setContentsMargins(px, 0, px, 0)
    (row.addLayout if isinstance(item, QHBoxLayout | QVBoxLayout) else row.addWidget)(item)
    return row


# --- small pieces ----------------------------------------------------------------------------
class ModeGlyph(QWidget):
    """A screen outline whose picture morphs between 16:9, 4:3 with bars and stretched 4:3."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 40)
        self._w = 1.0          # picture width relative to the screen
        self._active = 0.0
        self._anim = QVariantAnimation(self, duration=550, easingCurve=QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._step)
        self._from = (1.0, 0.0)
        self._to = (1.0, 0.0)

    def _step(self, t):
        t = float(t)
        self._w = _lerp(self._from[0], self._to[0], t)
        self._active = _lerp(self._from[1], self._to[1], t)
        self.update()

    def set_mode(self, width_ratio: float, active: bool):
        target = (width_ratio, 1.0 if active else 0.0)
        if target == self._to:
            return
        self._from, self._to = (self._w, self._active), target
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        screen = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(qc("#3A3F4B"), 1.2))
        p.setBrush(qc("#060608"))
        p.drawRoundedRect(screen, 5, 5)
        gw = screen.width() * self._w
        pic = QRectF(screen.center().x() - gw / 2, screen.top() + 3, gw, screen.height() - 6)
        pic = pic.adjusted(3, 0, -3, 0)
        col = _mix(qc(theme.FAINT), qc(theme.ACCENT), self._active)
        fill = QColor(col)
        fill.setAlphaF(0.22 + 0.2 * self._active)
        p.setPen(QPen(col, 1.6))
        p.setBrush(fill)
        p.drawRoundedRect(pic, 3, 3)


class TitleButtons(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        for glyph, slot, oid, tip in ((ICON_MIN, window.showMinimized, None, "Свернуть"),
                                      (ICON_CLOSE, window.close, "CloseBtn", "Закрыть")):
            b = _button(glyph, "icon", slot)
            b.setToolTip(tip)
            if oid:
                b.setObjectName(oid)
            lay.addWidget(b)


# --- settings panel ----------------------------------------------------------------------------
class SettingsPanel(QWidget):
    """Slides in from the right over a dimmed main screen."""
    closed = Signal()

    def __init__(self, controller: Controller, parent: QWidget):
        super().__init__(parent)
        self.c = controller
        self.setGeometry(0, 0, WIN_W, WIN_H)
        self.hide()

        self.scrim = QWidget(self)
        self.scrim.setGeometry(self.rect())
        self.scrim.setStyleSheet("background: rgba(0,0,0,0.55);")
        self.scrim.mousePressEvent = lambda e: self.close_panel()
        self._scrim_fx = QGraphicsOpacityEffect(self.scrim)
        self.scrim.setGraphicsEffect(self._scrim_fx)

        self.panel = QFrame(self)
        self.panel.setObjectName("Panel")
        self.panel_w = 460
        self.panel.setGeometry(WIN_W, 0, self.panel_w, WIN_H)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(34, 30, 34, 26)
        lay.setSpacing(0)

        head = QHBoxLayout()
        title = QLabel("НАСТРОЙКИ")
        title.setFont(theme.heading_font(30, 2))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(_button(ICON_CLOSE, "icon", self.close_panel))
        lay.addLayout(head)
        lay.addSpacing(18)

        cfg = controller.cfg
        lay.addWidget(_label("ИЗОБРАЖЕНИЕ", "cap"))
        lay.addSpacing(6)
        self._option(lay, "Растягивать на весь экран",
                     "Картинка 4:3 занимает весь монитор, как в CS2. Если выключить — по бокам "
                     "будут чёрные полосы.", cfg.stretch_mode, controller.set_stretch)
        lay.addSpacing(16)
        lay.addWidget(_label("ЗАПУСК", "cap"))
        lay.addSpacing(6)
        self._option(lay, "Включать 4:3 при запуске игры",
                     "Режим включится сам, как только откроется Rob-Run.",
                     cfg.auto_apply_on_launch, lambda v: controller.store.update(auto_apply_on_launch=v))
        self.sw_autostart = self._option(lay, "Запускать вместе с Windows",
                                         "Приложение будет тихо ждать в трее.",
                                         config.autostart_enabled(), self._set_autostart)
        self._option(lay, "Сворачивать в трей при закрытии",
                     "Крестик не закрывает приложение, а прячет его возле часов.",
                     cfg.minimize_to_tray, lambda v: controller.store.update(minimize_to_tray=v))
        lay.addSpacing(16)
        lay.addWidget(_label("ИГРА", "cap"))
        lay.addSpacing(8)
        game_row = QHBoxLayout()
        game_row.setSpacing(10)
        self.game_dot = StatusDot()
        game_row.addWidget(self.game_dot)
        self.game_found = _label("", "optTitle")
        game_row.addWidget(self.game_found, 1)
        lay.addLayout(game_row)
        lay.addSpacing(10)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(_button("Указать вручную", "soft", self._browse))
        btns.addWidget(_button("Найти автоматически", "soft", self._detect))
        btns.addStretch(1)
        lay.addLayout(btns)
        lay.addStretch(1)
        lay.addWidget(_label(f"Версия {APP_VERSION}", "tiny"))

        self._slide = QPropertyAnimation(self.panel, b"pos", self, duration=280,
                                         easingCurve=QEasingCurve.OutCubic)
        self._fade = QPropertyAnimation(self._scrim_fx, b"opacity", self, duration=280)
        self._slide.finished.connect(self._after_anim)
        self._closing = False

    def _option(self, layout, title: str, desc: str, checked: bool, on_change) -> Switch:
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(_label(title, "optTitle"))
        d = _label(desc, "optDesc")
        d.setWordWrap(True)
        text.addWidget(d)
        row.addLayout(text, 1)
        sw = Switch()
        sw.setChecked(checked)
        sw.toggled.connect(on_change)
        row.addWidget(sw, 0, Qt.AlignVCenter)
        layout.addLayout(row)
        return sw

    def open_panel(self):
        self._closing = False
        self.show()
        self.raise_()
        self._animate(WIN_W - self.panel_w, 1.0)

    def close_panel(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        self._animate(WIN_W, 0.0)

    def _animate(self, x: int, opacity: float):
        self._slide.stop()
        self._slide.setStartValue(self.panel.pos())
        self._slide.setEndValue(QPoint(x, 0))
        self._slide.start()
        self._fade.stop()
        self._fade.setStartValue(self._scrim_fx.opacity())
        self._fade.setEndValue(opacity)
        self._fade.start()

    def _after_anim(self):
        if self._closing:
            self.hide()
            self._closing = False
            self.closed.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_panel()
        else:
            super().keyPressEvent(e)

    def _set_autostart(self, on: bool):
        try:
            config.set_autostart(on)
            self.c.store.update(launch_with_windows=on)
            log.info("Autostart %s", "enabled" if on else "disabled")
        except OSError as e:
            log.error("Could not change autostart: %s", e)
            self.sw_autostart.setChecked(not on)

    def _browse(self):
        start = self.c.install.folder if self.c.install else "C:\\"
        path, _ = QFileDialog.getOpenFileName(self, "Где находится Rob-Run?", str(start),
                                              "Игра Rob-Run (*.exe)")
        if path:
            self.c.set_game_exe(os.path.normpath(path))

    def _detect(self):
        if not self.c.auto_detect():
            self.game_found.setText("Не нашли игру в Steam — укажите её вручную")
            self.game_dot.set_color(theme.ACCENT, False)

    def show_snapshot(self, _s: Snapshot):
        inst = self.c.install
        if inst:
            self.game_found.setText("Rob-Run найдена" + (" в Steam" if inst.via_steam else ""))
            self.game_found.setToolTip(str(inst.exe))
            self.game_dot.set_color(theme.GREEN, False)
        else:
            self.game_found.setText("Игра не найдена")
            self.game_found.setToolTip("")
            self.game_dot.set_color(theme.FAINT, False)


# --- developer window ------------------------------------------------------------------------
class DeveloperWindow(QWidget):
    """Technical state and the live log. Opened with Ctrl+Shift+D or --dev."""

    def __init__(self, bridge: QtLogBridge):
        super().__init__(None, Qt.Window)
        self.setWindowTitle("Rob-Run 4:3 — режим разработчика")
        self.setWindowIcon(app_icon())
        self.resize(820, 520)
        self.setStyleSheet(f"background:{theme.BG};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        self.info = _label("", "optDesc")
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(3000)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(_button("Открыть папку с логом", "soft", lambda: os.startfile(LOG_PATH.parent)))
        row.addWidget(_button("Копировать", "soft",
                              lambda: QGuiApplication.clipboard().setText(self.view.toPlainText())))
        row.addStretch(1)
        lay.addLayout(row)
        bridge.line.connect(self.view.appendPlainText)
        try:
            tail = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            self.view.setPlainText("\n".join(tail))
        except OSError:
            pass

    def show_snapshot(self, s: Snapshot):
        self.info.setText(
            f"phase={s.phase.value}  running={s.running}  booting={s.booting}  stretched={s.stretched}\n"
            f"desktop={s.desktop}  game={s.game_res} ({s.game_mode}, {s.game_aspect})\n"
            f"{s.compat}\n{s.install_path}")


# --- main window --------------------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self, controller: Controller, bridge: QtLogBridge):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)
        self.c = controller
        self._quitting = False
        self._drag: QPoint | None = None
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(app_icon())
        self.setFixedSize(WIN_W, WIN_H)
        self.setStyleSheet(LOCAL_QSS)
        self._bg = self._prepare_background()

        self._build_content()
        self.titlebuttons = TitleButtons(self)
        self.titlebuttons.adjustSize()
        self.titlebuttons.move(WIN_W - self.titlebuttons.width() - 10, 10)

        self.settings = SettingsPanel(controller, self)
        self.settings.closed.connect(lambda: self.settings_btn.setFocus())
        self.dev = DeveloperWindow(bridge)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, activated=self.toggle_dev)
        QShortcut(QKeySequence("Escape"), self, activated=self.settings.close_panel)

        self._build_tray()
        controller.state_changed.connect(self._render)
        controller.notify.connect(self._notify)
        if "--dev" in sys.argv:
            self.dev.show()

    # -- background ------------------------------------------------------------------------------
    def _prepare_background(self) -> QPixmap:
        """Fit the artwork to the window height and push it right, so the characters sit in
        the right two-thirds and the left side stays calm for the controls."""
        canvas = QPixmap(WIN_W, WIN_H)
        canvas.fill(qc(theme.BG))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        art = QPixmap(str(asset("background.webp")))
        if not art.isNull():
            scaled = art.scaledToHeight(WIN_H, Qt.SmoothTransformation)
            x0 = 150
            p.drawPixmap(x0, 0, scaled)
            # soften the hard left edge of the artwork
            edge = QLinearGradient(x0, 0, x0 + 90, 0)
            edge.setColorAt(0, qc(theme.BG))
            edge.setColorAt(1, qc(theme.BG, 0))
            p.fillRect(QRectF(x0, 0, 90, WIN_H), edge)
        # readable left column
        left = QLinearGradient(0, 0, WIN_W, 0)
        left.setColorAt(0.00, qc(theme.BG, 250))
        left.setColorAt(0.30, qc(theme.BG, 225))
        left.setColorAt(0.52, qc(theme.BG, 60))
        left.setColorAt(0.68, qc(theme.BG, 0))
        p.fillRect(canvas.rect(), left)
        # a touch of depth top and bottom
        vert = QLinearGradient(0, 0, 0, WIN_H)
        vert.setColorAt(0.0, qc("#000000", 90))
        vert.setColorAt(0.18, qc("#000000", 0))
        vert.setColorAt(0.82, qc("#000000", 0))
        vert.setColorAt(1.0, qc("#000000", 130))
        p.fillRect(canvas.rect(), vert)
        # warm glow behind the button area, echoing the artwork's orange
        glow = QRadialGradient(250, WIN_H * 0.78, 420)
        glow.setColorAt(0, qc(theme.ACCENT, 26))
        glow.setColorAt(1, qc(theme.ACCENT, 0))
        p.fillRect(canvas.rect(), glow)
        p.end()
        return canvas

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    # -- layout ----------------------------------------------------------------------------------------
    def _build_content(self):
        col = QWidget(self)
        col.setGeometry(50, 0, 498, WIN_H)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 44, 0, 32)
        lay.setSpacing(0)

        lay.addStretch(1)

        title = QLabel("РЕЖИМ 4:3")
        title.setFont(theme.heading_font(76, 2))
        lay.addLayout(_inset(title))
        lay.addSpacing(6)
        sub = _label("Одно нажатие — и игра в 1440×1080.\nРабочий стол Windows остаётся как был.", "sub")
        lay.addLayout(_inset(sub))
        lay.addSpacing(30)

        # status: game + mode
        card = QFrame()
        card.setObjectName("Glass")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(22, 16, 22, 16)
        cl.setSpacing(0)
        game = QVBoxLayout()
        game.setSpacing(6)
        game.addWidget(_label("ИГРА", "cap"))
        gr = QHBoxLayout()
        gr.setSpacing(9)
        self.dot = StatusDot()
        gr.addWidget(self.dot)
        self.game_status = _label("—", "big")
        gr.addWidget(self.game_status)
        gr.addStretch(1)
        game.addLayout(gr)
        cl.addLayout(game, 1)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: rgba(255,255,255,0.08);")
        cl.addWidget(sep)
        cl.addSpacing(22)
        mode = QVBoxLayout()
        mode.setSpacing(6)
        mode.addWidget(_label("РЕЖИМ", "cap"))
        self.mode_text = _label("—", "big")
        mode.addWidget(self.mode_text)
        cl.addLayout(mode, 1)
        self.glyph = ModeGlyph()
        cl.addWidget(self.glyph, 0, Qt.AlignVCenter)
        lay.addLayout(_inset(card))
        lay.addSpacing(22)

        self.button = ToggleButton()
        self.button.clicked.connect(self.c.toggle)
        lay.addWidget(self.button)
        lay.addSpacing(8)

        self.message = _label("", "sub")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(40)
        self.message.setStyleSheet("font-size: 13px;")
        lay.addLayout(_inset(self.message))
        lay.addStretch(2)

        foot = QHBoxLayout()
        self.settings_btn = _button("Настройки", "soft", lambda: self.settings.open_panel())
        foot.addWidget(self.settings_btn)
        foot.addStretch(1)
        lay.addLayout(_inset(foot))

    def showEvent(self, e):
        super().showEvent(e)
        win32.style_dark_frame(int(self.winId()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 120:
            handle = self.windowHandle()
            if handle and handle.startSystemMove():
                return
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None

    def toggle_dev(self):
        self.dev.setVisible(not self.dev.isVisible())
        if self.dev.isVisible():
            self.dev.raise_()

    # -- state -------------------------------------------------------------------------------------------
    def _render(self, s: Snapshot):
        stretch = self.c.cfg.stretch_mode
        if s.booting:
            self.game_status.setText("Запускается…")
            self.dot.set_color(theme.ACCENT, True)
        elif s.running:
            self.game_status.setText("Запущена")
            self.dot.set_color(theme.GREEN, s.phase == Phase.ACTIVE)
        else:
            self.game_status.setText("Не запущена")
            self.dot.set_color(theme.FAINT, False)

        mode, ratio, lit = "—", 1.0, False
        if s.phase == Phase.ACTIVE:
            mode, ratio, lit = ("4:3 на весь экран", 1.0, True) if stretch else ("4:3 с полосами", 0.75, True)
        elif s.phase == Phase.APPLYING:
            mode = "Переключаем…"
        elif s.phase == Phase.RESTORING:
            mode = "Возвращаем…"
        elif s.phase == Phase.LAUNCHING:
            mode = "Ждём игру…"
        elif s.running and not s.booting:
            mode = "Обычный 16:9"
        self.mode_text.setText(mode)
        self.mode_text.setStyleSheet(f"color:{theme.ACCENT};" if lit else "")
        self.glyph.set_mode(ratio, lit)

        if s.phase == Phase.ACTIVE:
            self.button.set_state("disable", "ВЫКЛЮЧИТЬ 4:3", "Вернуть обычный режим 16:9")
        elif s.phase == Phase.APPLYING:
            self.button.set_state("busy", "ВКЛЮЧАЕМ…", "Пара секунд")
        elif s.phase == Phase.RESTORING:
            self.button.set_state("busy", "ВЫКЛЮЧАЕМ…", "Пара секунд")
        elif s.phase == Phase.LAUNCHING:
            self.button.set_state("enable", "ЖДЁМ ИГРУ…", "Нажмите, чтобы отменить")
        else:
            self.button.set_state("enable", "ВКЛЮЧИТЬ 4:3",
                                  "Только для игры · рабочий стол не меняется" if s.running
                                  else "Rob-Run запустится автоматически")

        color = {"ok": theme.GREEN, "warn": theme.ACCENT, "error": theme.RED}.get(s.message_kind, "#A9AFBC")
        self.message.setStyleSheet(f"font-size: 13px; color:{color};")
        self.message.setText(s.message)

        self.settings.show_snapshot(s)
        if self.dev.isVisible():
            self.dev.show_snapshot(s)

        active = s.phase == Phase.ACTIVE
        self.tray_toggle.setText({Phase.ACTIVE: "Выключить 4:3", Phase.LAUNCHING: "Отменить ожидание"}
                                 .get(s.phase, "Включить 4:3"))
        self.tray_toggle.setEnabled(s.phase in (Phase.IDLE, Phase.ACTIVE, Phase.LAUNCHING))
        if active != self._tray_active:
            self._tray_active = active
            self.tray.setIcon(app_icon(active))
            self.tray.setToolTip(f"Rob-Run 4:3 — {'включён' if active else 'выключен'}")

    # -- tray ---------------------------------------------------------------------------------------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Rob-Run 4:3 — выключен")
        menu = QMenu()
        menu.addAction("Открыть", self.bring_to_front)
        self.tray_toggle = QAction("Включить 4:3", menu)
        self.tray_toggle.triggered.connect(self.c.toggle)
        menu.addAction(self.tray_toggle)
        menu.addSeparator()
        menu.addAction("Выход", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.bring_to_front() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()
        self._tray_active = None

    def _notify(self, title: str, text: str, kind: str):
        icon = {"error": QSystemTrayIcon.Critical, "warn": QSystemTrayIcon.Warning}.get(
            kind, QSystemTrayIcon.Information)
        self.tray.showMessage(title, text, icon, 4000)

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # -- closing ------------------------------------------------------------------------------------------
    def closeEvent(self, e):
        if not self._quitting and self.c.cfg.minimize_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            e.ignore()
            self.hide()
            if not self.c.cfg.tray_hint_shown:
                self.tray.showMessage("Rob-Run 4:3", "Приложение работает в трее. Чтобы выйти — "
                                      "нажмите на значок правой кнопкой.", QSystemTrayIcon.Information, 4000)
                self.c.store.update(tray_hint_shown=True)
            return
        self.quit()
        e.accept()

    def quit(self):
        if self._quitting:
            return
        self._quitting = True
        self.hide()
        self.dev.hide()
        self.c.shutdown()
        self.tray.hide()
        QApplication.quit()
