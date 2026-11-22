"""Custom painted widgets: the main toggle button, aspect preview, switches."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Property,
                            QPropertyAnimation)
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QFont)
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from ui import theme
from ui.theme import qc


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    return QColor(int(_lerp(c1.red(), c2.red(), t)), int(_lerp(c1.green(), c2.green(), t)),
                  int(_lerp(c1.blue(), c2.blue(), t)), int(_lerp(c1.alpha(), c2.alpha(), t)))


class ToggleButton(QAbstractButton):
    """The big ENABLE 4:3 / DISABLE 4:3 button.

    mode: "enable" (amber), "disable" (armed, green), "busy" (animated sweep)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._mode = "enable"
        self._title = "ENABLE 4:3"
        self._subtitle = "1440 × 1080  ·  game only"
        self._hover = 0.0
        self._press = 0.0
        self._armed = 0.0      # 0 = enable look, 1 = disable look
        self._sweep = 0.0
        self._pulse = 0.0

        self._hover_anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._hover_anim.valueChanged.connect(lambda v: self._set("_hover", v))
        self._press_anim = QVariantAnimation(self, duration=120, easingCurve=QEasingCurve.OutCubic)
        self._press_anim.valueChanged.connect(lambda v: self._set("_press", v))
        self._armed_anim = QVariantAnimation(self, duration=420, easingCurve=QEasingCurve.InOutCubic)
        self._armed_anim.valueChanged.connect(lambda v: self._set("_armed", v))
        self._sweep_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1100,
                                             loopCount=-1)
        self._sweep_anim.valueChanged.connect(lambda v: self._set("_sweep", v))
        self._pulse_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=2600,
                                             loopCount=-1)
        self._pulse_anim.valueChanged.connect(lambda v: self._set("_pulse", v))
        self._pulse_anim.start()

    def _set(self, name, value):
        setattr(self, name, float(value))
        self.update()

    def _animate(self, anim: QVariantAnimation, current: float, target: float):
        anim.stop()
        anim.setStartValue(current)
        anim.setEndValue(target)
        anim.start()

    def set_state(self, mode: str, title: str, subtitle: str):
        if mode != self._mode:
            if mode == "busy":
                self._sweep_anim.start()
            else:
                self._sweep_anim.stop()
                self._sweep = 0.0
            if mode in ("enable", "disable"):
                self._animate(self._armed_anim, self._armed, 1.0 if mode == "disable" else 0.0)
        self._mode = mode
        self._title = title
        self._subtitle = subtitle
        self.setEnabled(mode != "busy")
        self.setCursor(Qt.WaitCursor if mode == "busy" else Qt.PointingHandCursor)
        self.update()

    def sizeHint(self):
        return QSize(360, 86)

    def enterEvent(self, e):
        self._animate(self._hover_anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._animate(self._press_anim, self._press, 1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._animate(self._press_anim, self._press, 0.0)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glow_pad = 14.0
        scale = 1.0 - 0.015 * self._press
        r = QRectF(self.rect()).adjusted(glow_pad, glow_pad / 2, -glow_pad, -glow_pad / 2)
        r = QRectF(r.center().x() - r.width() * scale / 2, r.center().y() - r.height() * scale / 2,
                   r.width() * scale, r.height() * scale)
        radius = 16.0
        t = self._armed
        busy = self._mode == "busy"

        # soft glow
        glow_col = _mix(qc(theme.ACCENT), qc(theme.GREEN), t)
        breathe = 0.5 + 0.5 * abs(1 - 2 * self._pulse)
        strength = 0.10 + 0.10 * self._hover + 0.06 * breathe * t
        if busy:
            strength = 0.12
        for i in range(7, 0, -1):
            g = QColor(glow_col)
            g.setAlphaF(strength * (1 - i / 8) ** 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(-i * 2, -i * 1.2, i * 2, i * 1.2), radius + i * 2, radius + i * 2)

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        # body: amber gradient (enable) cross-fades into a dark armed panel (disable)
        amber = QLinearGradient(r.topLeft(), r.bottomRight())
        lift = 0.12 * self._hover
        amber.setColorAt(0, _mix(qc(theme.ACCENT), QColor("#FFB27A"), lift))
        amber.setColorAt(1, _mix(qc(theme.ACCENT_2), qc(theme.ACCENT), lift))
        p.fillPath(path, QBrush(amber))
        if t > 0:
            dark = QLinearGradient(r.topLeft(), r.bottomLeft())
            dark.setColorAt(0, qc("#16201B", int(255 * t)))
            dark.setColorAt(1, qc("#0F1512", int(255 * t)))
            p.fillPath(path, QBrush(dark))
        if busy:
            dim = QColor(0, 0, 0, 90)
            p.fillPath(path, dim)
            x = r.left() - r.width() * 0.4 + self._sweep * r.width() * 1.8
            sweep = QLinearGradient(QPointF(x - 90, 0), QPointF(x + 90, 0))
            sweep.setColorAt(0, QColor(255, 255, 255, 0))
            sweep.setColorAt(0.5, QColor(255, 255, 255, 70))
            sweep.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillPath(path, QBrush(sweep))

        # top sheen
        sheen = QLinearGradient(r.topLeft(), QPointF(r.left(), r.center().y()))
        sheen.setColorAt(0, QColor(255, 255, 255, int(46 * (1 - t) + 10 * t)))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))

        border = _mix(QColor(255, 200, 160, 120), qc(theme.GREEN, int(150 + 80 * self._hover)), t)
        p.setPen(QPen(border, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # aspect glyph on the left
        glyph_h = r.height() * 0.42
        gw_wide, gw_narrow = glyph_h * 16 / 9, glyph_h * 4 / 3
        gx = r.left() + 26
        gy = r.center().y() - glyph_h / 2
        text_dark = QColor("#1A1206")
        fg = _mix(text_dark, qc(theme.GREEN), t)
        p.setPen(QPen(_mix(QColor(26, 18, 6, 110), qc(theme.GREEN, 110), t), 1.4, Qt.DashLine))
        p.drawRoundedRect(QRectF(gx, gy, gw_wide, glyph_h), 3, 3)
        inner_w = _lerp(gw_wide, gw_narrow, t)
        p.setPen(QPen(fg, 2.0))
        p.drawRoundedRect(QRectF(gx + (gw_wide - inner_w) / 2, gy, inner_w, glyph_h), 3, 3)

        # text
        text_left = gx + gw_wide + 22
        text_rect = QRectF(text_left, r.top(), r.right() - text_left - 18, r.height())
        p.setPen(_mix(text_dark, qc(theme.TEXT), t) if not busy else QColor(255, 255, 255, 230))
        p.setFont(theme.heading_font(30, 2.0))
        p.drawText(text_rect.adjusted(0, 0, 0, -16), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        p.setFont(theme.body_font(12, QFont.DemiBold))
        sub = _mix(QColor(26, 18, 6, 170), qc(theme.MUTED), t) if not busy else QColor(255, 255, 255, 170)
        p.setPen(sub)
        p.drawText(text_rect.adjusted(1, 30, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self._subtitle)


class Switch(QAbstractButton):
    """Animated on/off switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self, duration=160,
                                        easingCurve=QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on: bool):  # noqa: N802 - Qt naming
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        track = _mix(qc(theme.SURFACE_2), qc(theme.ACCENT), self._pos)
        p.setPen(QPen(_mix(qc(theme.BORDER), qc(theme.ACCENT), self._pos), 1))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = _lerp(r.left() + 3, r.right() - 3 - d, self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(_mix(qc(theme.MUTED), QColor("#1A1206"), self._pos))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = qc(theme.FAINT)
        self._phase = 0.0
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1600, loopCount=-1)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._phase = float(v)
        self.update()

    def set_color(self, color: str, pulsing: bool):
        self._color = qc(color)
        if pulsing and self._anim.state() != QVariantAnimation.Running:
            self._anim.start()
        elif not pulsing:
            self._anim.stop()
            self._phase = 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        halo = QColor(self._color)
        halo.setAlphaF(0.35 * (1 - self._phase))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        rr = 2 + 3 * self._phase
        p.drawEllipse(QRectF(5 - rr, 5 - rr, 2 * rr, 2 * rr))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(2, 2, 6, 6))


def asset(name: str) -> Path:
    """Bundled file; works from source and from the PyInstaller one-file build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "assets" / name


_icon_cache: dict[bool, QIcon] = {}


def app_icon(active: bool = False) -> QIcon:
    """The Rob-Run app icon. While 4:3 is on, a green dot is added (tray, taskbar)."""
    if active in _icon_cache:
        return _icon_cache[active]
    base = QPixmap(str(asset("icon.png")))
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = base.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if active:
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            d = max(6.0, size * 0.36)
            dot = QRectF(size - d, size - d, d, d)
            p.setPen(QPen(QColor("#08080A"), max(1.0, size * 0.06)))
            p.setBrush(qc(theme.GREEN))
            p.drawEllipse(dot.adjusted(0.5, 0.5, -0.5, -0.5))
            p.end()
        icon.addPixmap(pm)
    _icon_cache[active] = icon
    return icon
