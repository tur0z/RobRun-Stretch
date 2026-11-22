"""Palette, fonts and the global stylesheet."""
from PySide6.QtGui import QColor, QFont

BG = "#08080A"
SURFACE = "#121419"
SURFACE_2 = "#181B22"
BORDER = "#242833"
TEXT = "#ECEEF3"
MUTED = "#7E8596"
FAINT = "#4A5060"
ACCENT = "#FF7A1A"
ACCENT_2 = "#E2440A"
GREEN = "#3DDC84"
RED = "#FF4D5E"

HEADING_FAMILY = "Bahnschrift SemiBold Condensed"
HEADING_LIGHT_FAMILY = "Bahnschrift SemiLight SemiCondensed"
BODY_FAMILY = "Segoe UI Variable Text"
MONO_FAMILY = "Cascadia Mono"


def qc(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def heading_font(px: int, spacing: float = 1.0) -> QFont:
    f = QFont(HEADING_FAMILY)
    f.setPixelSize(px)
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def body_font(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(BODY_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


STYLESHEET = f"""
* {{ color: {TEXT}; }}
#Root {{
    background: {BG};
    border: 1px solid {BORDER};
}}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="key"] {{ color: {MUTED}; font-size: 13px; }}
QLabel[role="value"] {{ color: {TEXT}; font-size: 13px; font-weight: 600; }}
QLabel[role="section"] {{
    color: {MUTED}; font-family: "{HEADING_FAMILY}"; font-size: 12px; letter-spacing: 2px;
}}
QLabel[role="message"] {{ color: {MUTED}; font-size: 12px; }}

#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
#Divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; }}

QPushButton[kind="ghost"] {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 14px;
    color: {MUTED};
    font-size: 12px;
    font-weight: 600;
}}
QPushButton[kind="ghost"]:hover {{
    border-color: {ACCENT};
    color: {TEXT};
    background: rgba(255,122,26,0.06);
}}
QPushButton[kind="ghost"]:pressed {{ background: rgba(255,122,26,0.12); }}

QPushButton[kind="icon"] {{
    background: transparent; border: none; border-radius: 8px;
    color: {MUTED}; font-family: "Segoe MDL2 Assets"; font-size: 12px;
    min-width: 36px; min-height: 30px;
}}
QPushButton[kind="icon"]:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#CloseBtn:hover {{ background: {RED}; color: white; }}

QPushButton[kind="nav"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    color: {MUTED};
    font-size: 12px;
    font-weight: 600;
    text-align: left;
}}
QPushButton[kind="nav"]:hover {{ border-color: {FAINT}; color: {TEXT}; background: {SURFACE_2}; }}

QPlainTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 8px;
    font-family: "{MONO_FAMILY}", Consolas;
    font-size: 11px;
    color: #B9BFCC;
    selection-background-color: rgba(255,122,26,0.35);
}}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    height: 0; background: none;
}}
QToolTip {{
    background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 6px 8px; border-radius: 6px;
}}
QMenu {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
}}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: {SURFACE_2}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
"""
