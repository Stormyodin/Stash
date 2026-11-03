"""Colors, fonts and the global stylesheet (macOS-style dark)."""
from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor, QFont

from core.models import Category

BG = "#1C1C1E"
SIDEBAR = "#252526"
CARD = "#2C2C2E"
CARD_HOVER = "#323234"
BORDER = "#3A3A3C"
ROW_ALT = "#242424"
TEXT = "#F2F2F7"
TEXT2 = "#8E8E93"
ACCENT = "#0A84FF"
DANGER = "#FF453A"
SUCCESS = "#32D74B"

FONT_FAMILIES = ["SF Pro Display", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI Variable",
                 "Segoe UI", "Inter", "Helvetica Neue", "Noto Sans", "DejaVu Sans"]

EASE_OUT = QEasingCurve.OutCubic
EASE_IN = QEasingCurve.InCubic

# Badge colors per category (macOS system palette)
CATEGORY_COLORS = {
    Category.GAMES: "#BF5AF2",
    Category.APPS: "#0A84FF",
    Category.DEVTOOLS: "#30D158",
    Category.MEDIA: "#FF9F0A",
    Category.CREATIVE: "#FF375F",
    Category.PORTABLE: "#64D2FF",
    Category.OTHER: "#8E8E93",
}

_font_cache: dict[tuple, QFont] = {}


def font(px: int = 13, weight: QFont.Weight = QFont.Normal) -> QFont:
    key = (px, weight)
    f = _font_cache.get(key)
    if f is None:
        f = QFont()
        f.setFamilies(FONT_FAMILIES)
        f.setPixelSize(px)
        f.setWeight(weight)
        f.setHintingPreference(QFont.PreferNoHinting)
        f.setStyleStrategy(QFont.PreferAntialias)
        _font_cache[key] = f
    return QFont(f)


def qc(hex_: str, alpha: int | None = None) -> QColor:
    c = QColor(hex_)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")


def stylesheet() -> str:
    return f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; }}
QWidget#Root {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid #2F2F31; }}
QWidget#Main {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[role="secondary"] {{ color: {TEXT2}; font-size: 11px; }}
QLabel[role="title"] {{ font-size: 20px; font-weight: 600; }}
QLabel[role="section"] {{ color: {TEXT2}; font-size: 11px; font-weight: 600; letter-spacing: 0.4px; }}

QLineEdit {{
    background: rgba(255,255,255,0.06); border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; selection-background-color: {ACCENT}; color: {TEXT};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; background: rgba(255,255,255,0.08); }}

QComboBox {{
    background: rgba(255,255,255,0.06); border: 1px solid {BORDER}; border-radius: 8px;
    padding: 5px 28px 5px 10px; min-width: 120px; color: {TEXT};
}}
QComboBox:hover {{ background: rgba(255,255,255,0.09); }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url("{ASSETS}/chevron.png"); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    background: #2A2A2C; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px;
    selection-background-color: {ACCENT}; color: {TEXT};
}}

QPushButton {{
    background: rgba(255,255,255,0.08); border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 14px; color: {TEXT};
}}
QPushButton:hover {{ background: rgba(255,255,255,0.12); }}
QPushButton:pressed {{ background: rgba(255,255,255,0.05); }}
QPushButton[kind="primary"] {{ background: {ACCENT}; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: #2490FF; }}
QPushButton[kind="primary"]:pressed {{ background: #0070E0; }}
QPushButton[kind="danger"] {{ background: rgba(255,69,58,0.14); border: 1px solid rgba(255,69,58,0.45); color: {DANGER}; }}
QPushButton[kind="danger"]:hover {{ background: rgba(255,69,58,0.24); }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px 4px 0; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.32); }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

QListView {{ background: transparent; border: none; }}

QMenu {{
    background: #2A2A2C; border: 1px solid {BORDER}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolTip {{
    background: #2A2A2C; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px;
}}
QMessageBox {{ background: #2A2A2C; }}
"""
