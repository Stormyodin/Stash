"""Ctrl+K command palette: blurred backdrop, fuzzy search over everything, keyboard driven."""
from __future__ import annotations

import heapq

from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QModelIndex, QParallelAnimationGroup, QPoint,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QLabel, QListView, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from core.models import AppEntry

from . import theme
from .delegates import CAT_COLORS, C_TEXT, C_TEXT2, draw_badge, draw_highlighted
from .fuzzy import match_entry
from .icons import IconCache, paint_placeholder
from .widgets import SearchField

MAX_RESULTS = 12
ROW_H = 46
PANEL_W = 600


class _ResultModel(QAbstractListModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[AppEntry, tuple[int, ...]]] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == Qt.UserRole:
            return self.rows[index.row()]
        return None

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


class _ResultDelegate(QStyledItemDelegate):
    def __init__(self, icons: IconCache, parent=None) -> None:
        super().__init__(parent)
        self.icons = icons
        self.f_name = theme.font(14, QFont.Medium)
        self.f_small = theme.font(11)
        self.f_badge = theme.font(10, QFont.DemiBold)

    def sizeHint(self, option, index) -> QSize:
        return QSize(PANEL_W - 20, ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        e, idx = index.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(option.rect).adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(r, 9, 9)
        icon = QRectF(r.x() + 10, r.center().y() - 14, 28, 28)
        pm = self.icons.get(e)
        if pm is not None:
            p.drawPixmap(icon.toRect(), pm)
        else:
            paint_placeholder(p, icon, e.name, e.id)
        x = int(icon.right()) + 12
        w = int(r.right()) - x - 110
        p.setFont(self.f_name)
        txt = QColor(255, 255, 255) if selected else C_TEXT
        if selected:
            p.setPen(txt)
            p.drawText(QRect(x, int(r.y()) + 5, w, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(e.name, Qt.ElideRight, w))
        else:
            draw_highlighted(p, QRect(x, int(r.y()) + 5, w, 20), e.name, idx, txt)
        p.setFont(self.f_small)
        p.setPen(QColor(255, 255, 255, 200) if selected else C_TEXT2)
        path = e.exe_path or e.install_path or e.launcher
        p.drawText(QRect(x, int(r.y()) + 24, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(path, Qt.ElideMiddle, w))
        col = QColor(255, 255, 255) if selected else CAT_COLORS.get(e.category, C_TEXT2)
        draw_badge(p, int(r.right()) - 12, int(r.center().y()), e.category.value, col, self.f_badge, right_align=True)
        p.restore()


class CommandPalette(QWidget):
    launchRequested = Signal(object)
    revealRequested = Signal(object)

    def __init__(self, icons: IconCache, entries_provider, parent: QWidget) -> None:
        super().__init__(parent)
        self.entries_provider = entries_provider
        self._backdrop: QPixmap | None = None
        self.is_open = False
        self.hide()

        self.panel = QFrame(self)
        self.panel.setObjectName("Palette")
        self.panel.setStyleSheet(f"#Palette{{background: rgba(28,28,30,0.97); border: 1px solid {theme.BORDER};"
                                 f" border-radius: 16px;}}")
        self.panel.setFixedWidth(PANEL_W)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.input = SearchField("Search apps, games, tools…")
        self.input.setFixedHeight(42)
        self.input.setFont(theme.font(16))
        self.input.setStyleSheet("QLineEdit{background:transparent;border:none;font-size:16px;padding-left:6px;}")
        self.input.installEventFilter(self)
        lay.addWidget(self.input)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{theme.BORDER};border:none;")
        lay.addWidget(sep)
        self.model = _ResultModel()
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(_ResultDelegate(icons, self.list))
        self.list.setUniformItemSizes(True)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.clicked.connect(lambda i: self._launch(i.row()))
        lay.addWidget(self.list)
        self.hint = QLabel("↑↓ navigate    ↵ launch    ⇧↵ show in Stash    esc close")
        self.hint.setProperty("role", "secondary")
        self.hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.hint)
        icons.ready.connect(lambda _i: self.list.viewport().update() if self.is_open else None)

        self._debounce = QTimer(self, singleShot=True, interval=40)
        self._debounce.timeout.connect(self._refresh)
        self.input.textChanged.connect(lambda _t: self._debounce.start())

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._group = QParallelAnimationGroup(self)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self._group)
        self._slide = QPropertyAnimation(self.panel, b"pos", self._group)
        for a in (self._fade, self._slide):
            a.setDuration(150)
            self._group.addAnimation(a)
        self._group.finished.connect(self._on_anim_done)

    # ---- open / close -----------------------------------------------------
    def toggle(self) -> None:
        self.close_palette() if self.is_open else self.open_palette()

    def open_palette(self) -> None:
        par = self.parentWidget()
        self.setGeometry(par.rect())
        # one-off cheap blur: downscale + smooth upscale of the window snapshot
        self.hide()
        snap = par.grab()
        small = snap.scaled(max(1, snap.width() // 12), max(1, snap.height() // 12), Qt.IgnoreAspectRatio,
                            Qt.SmoothTransformation)
        self._backdrop = small.scaled(snap.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._backdrop.setDevicePixelRatio(snap.devicePixelRatio())
        del snap, small
        self.is_open = True
        self.input.blockSignals(True)
        self.input.clear()
        self.input.blockSignals(False)
        self._refresh()
        self.panel.adjustSize()
        x = (self.width() - PANEL_W) // 2
        y = max(40, int(self.height() * 0.14))
        self._animate(QPoint(x, y - 24), QPoint(x, y), 0.0, 1.0, QEasingCurve.OutCubic)
        self.raise_()
        self.show()
        self.input.setFocus()

    def close_palette(self) -> None:
        if not self.is_open:
            return
        self.is_open = False
        p = self.panel.pos()
        self._animate(p, QPoint(p.x(), p.y() - 24), self._fx.opacity(), 0.0, QEasingCurve.InCubic)

    def _animate(self, p0, p1, o0, o1, curve) -> None:
        self._group.stop()
        self._slide.setStartValue(p0)
        self._slide.setEndValue(p1)
        self._slide.setEasingCurve(curve)
        self._fade.setStartValue(o0)
        self._fade.setEndValue(o1)
        self._fade.setEasingCurve(curve)
        self._group.start()

    def _on_anim_done(self) -> None:
        if not self.is_open:
            self.hide()
            self._backdrop = None  # free the snapshot
            self.model.set_rows([])

    # ---- results ----------------------------------------------------------
    def _refresh(self) -> None:
        q = self.input.text().strip().lower()
        entries = self.entries_provider()
        if not q:
            recent = sorted(entries, key=lambda e: (e.last_used is None, -(e.last_used.timestamp() if e.last_used
                                                                          else 0), e.name.casefold()))
            rows = [(e, ()) for e in recent[:MAX_RESULTS]]
        else:
            scored = []
            for e in entries:
                m = match_entry(q, e.name, e.publisher, e.install_path or e.exe_path)
                if m is not None:
                    scored.append((m[0], -len(e.name), e.id, e, m[1]))
            rows = [(t[3], t[4]) for t in heapq.nlargest(MAX_RESULTS, scored, key=lambda t: (t[0], t[1]))]
        self.model.set_rows(rows)
        n = len(rows)
        self.list.setFixedHeight(max(1, n) * ROW_H + 4 if n else 0)
        self.list.setVisible(n > 0)
        if n:
            self.list.setCurrentIndex(self.model.index(0))
        self.panel.adjustSize()

    def _launch(self, row: int, reveal: bool = False) -> None:
        if 0 <= row < len(self.model.rows):
            e = self.model.rows[row][0]
            self.close_palette()
            (self.revealRequested if reveal else self.launchRequested).emit(e)

    # ---- events -----------------------------------------------------------
    def eventFilter(self, obj, ev) -> bool:
        if obj is self.input and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            n = self.model.rowCount()
            cur = self.list.currentIndex().row()
            if k in (Qt.Key_Down, Qt.Key_Up) and n:
                cur = (cur + (1 if k == Qt.Key_Down else -1)) % n
                self.list.setCurrentIndex(self.model.index(cur))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._launch(cur, reveal=bool(ev.modifiers() & Qt.ShiftModifier))
                return True
            if k == Qt.Key_Escape:
                self.close_palette()
                return True
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev) -> None:
        if not self.panel.geometry().contains(ev.position().toPoint()):
            self.close_palette()

    def resizeEvent(self, ev) -> None:
        if self.is_open:
            self.panel.move((self.width() - PANEL_W) // 2, self.panel.y())

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        if self._backdrop is not None:
            p.drawPixmap(0, 0, self._backdrop)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        # subtle panel drop shadow
        p.setRenderHint(QPainter.Antialiasing)
        g = self.panel.geometry()
        for i, a in enumerate((40, 22, 10)):
            p.setPen(QPen(QColor(0, 0, 0, a), 3))
            d = 2 + i * 3
            p.drawRoundedRect(QRectF(g).adjusted(-d, -d + 4, d, d + 4), 16 + d, 16 + d)
