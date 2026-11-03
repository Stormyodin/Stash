"""Right-hand details panel that slides in over the content area."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core.models import AppEntry

from . import theme
from .icons import IconCache, draw_glyph, paint_placeholder
from .model import fmt_ago, fmt_date, fmt_size

PANEL_W = 300
SHADOW = 18


class _BigIcon(QWidget):
    def __init__(self, icons: IconCache, parent=None) -> None:
        super().__init__(parent)
        self.icons = icons
        self.entry: AppEntry | None = None
        self.setFixedSize(96, 96)
        icons.ready.connect(lambda i: self.update() if self.entry and i == self.entry.id else None)

    def paintEvent(self, e) -> None:
        if not self.entry:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pm = self.icons.get(self.entry)
        if pm is not None:
            p.drawPixmap(self.rect(), pm)
        else:
            paint_placeholder(p, QRectF(self.rect()), self.entry.name, self.entry.id)


class DetailsPanel(QWidget):
    launchRequested = Signal(object)
    folderRequested = Signal(object)
    copyRequested = Signal(object)
    uninstallRequested = Signal(object)
    closed = Signal()

    def __init__(self, icons: IconCache, parent: QWidget) -> None:
        super().__init__(parent)
        self.entry: AppEntry | None = None
        self.is_open = False
        self.setFixedWidth(PANEL_W + SHADOW)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(SHADOW + 22, 16, 22, 20)
        root.setSpacing(0)

        top = QHBoxLayout()
        top.addStretch()
        self.btn_close = QPushButton()
        self.btn_close.setIcon(draw_glyph("close", 12, QColor(theme.TEXT2)))
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("QPushButton{border-radius:13px;padding:0;background:rgba(255,255,255,0.06);"
                                     "border:none;} QPushButton:hover{background:rgba(255,255,255,0.14);}")
        self.btn_close.clicked.connect(self.close_panel)
        top.addWidget(self.btn_close)
        root.addLayout(top)

        self.icon = _BigIcon(icons)
        root.addWidget(self.icon, 0, Qt.AlignHCenter)
        root.addSpacing(14)
        self.name = QLabel()
        self.name.setProperty("role", "title")
        self.name.setWordWrap(True)
        self.name.setAlignment(Qt.AlignHCenter)
        root.addWidget(self.name)
        root.addSpacing(4)
        self.sub = QLabel()
        self.sub.setProperty("role", "secondary")
        self.sub.setAlignment(Qt.AlignHCenter)
        self.sub.setWordWrap(True)
        root.addWidget(self.sub)
        root.addSpacing(18)

        self.btn_launch = QPushButton("Launch")
        self.btn_launch.setProperty("kind", "primary")
        self.btn_launch.setFixedHeight(34)
        root.addWidget(self.btn_launch)
        root.addSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_folder = QPushButton("Open Folder")
        self.btn_copy = QPushButton("Copy Path")
        row.addWidget(self.btn_folder)
        row.addWidget(self.btn_copy)
        root.addLayout(row)
        root.addSpacing(20)

        card = QWidget()
        card.setObjectName("InfoCard")
        card.setStyleSheet(f"#InfoCard{{background:{theme.CARD};border:1px solid {theme.BORDER};border-radius:12px;}}")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(9)
        self.fields: dict[str, QLabel] = {}
        for r, key in enumerate(("Version", "Publisher", "Size", "Installed", "Last used", "Source", "Location")):
            k = QLabel(key)
            k.setProperty("role", "secondary")
            v = QLabel()
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.setFont(theme.font(12))
            grid.addWidget(k, r, 0, Qt.AlignTop | Qt.AlignLeft)
            grid.addWidget(v, r, 1)
            self.fields[key] = v
        grid.setColumnStretch(1, 1)
        root.addWidget(card)
        root.addStretch()
        self.btn_uninstall = QPushButton("Uninstall…")
        self.btn_uninstall.setProperty("kind", "danger")
        self.btn_uninstall.setFixedHeight(32)
        root.addWidget(self.btn_uninstall)

        for b in (self.btn_launch, self.btn_folder, self.btn_copy, self.btn_uninstall):
            b.setCursor(Qt.PointingHandCursor)
        self.btn_launch.clicked.connect(lambda: self.entry and self.launchRequested.emit(self.entry))
        self.btn_folder.clicked.connect(lambda: self.entry and self.folderRequested.emit(self.entry))
        self.btn_copy.clicked.connect(lambda: self.entry and self.copyRequested.emit(self.entry))
        self.btn_uninstall.clicked.connect(lambda: self.entry and self.uninstallRequested.emit(self.entry))

        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(200)
        self._anim.finished.connect(self._on_anim_done)
        self.hide()

    # ---- content ----------------------------------------------------------
    def set_entry(self, e: AppEntry) -> None:
        self.entry = e
        self.icon.entry = e
        self.icon.update()
        self.name.setText(e.name)
        self.sub.setText(" · ".join(x for x in (e.category.value, e.version and f"v{e.version}") if x))
        f = self.fields
        f["Version"].setText(e.version or "—")
        f["Publisher"].setText(e.publisher or "—")
        f["Size"].setText(fmt_size(e.size_bytes))
        f["Installed"].setText(fmt_date(e.install_date))
        f["Last used"].setText(fmt_ago(e.last_used) if e.last_used else "—")
        f["Source"].setText(e.source.value)
        loc = e.install_path or e.exe_path or e.launcher or "—"
        # allow wrapping inside long paths
        f["Location"].setText(loc.replace("\\", "\\\u200b").replace("/", "/\u200b"))
        f["Location"].setToolTip(loc)
        self.btn_launch.setEnabled(bool(e.exe_path or e.launcher))
        self.btn_folder.setEnabled(bool(e.install_path or e.exe_path))

    # ---- geometry / animation --------------------------------------------
    def _x_open(self) -> int:
        return self.parentWidget().width() - self.width()

    def reposition(self) -> None:
        par = self.parentWidget()
        self.setFixedHeight(par.height())
        if self._anim.state() != QPropertyAnimation.Running:
            self.move(self._x_open() if self.is_open else par.width(), 0)

    def open_for(self, e: AppEntry) -> None:
        self.set_entry(e)
        if self.is_open:
            return
        self.is_open = True
        self.setFixedHeight(self.parentWidget().height())
        self.raise_()
        self.show()
        self._slide(self.parentWidget().width(), self._x_open(), QEasingCurve.OutCubic)

    def close_panel(self) -> None:
        if not self.is_open:
            return
        self.is_open = False
        self._slide(self.x(), self.parentWidget().width(), QEasingCurve.InCubic, 170)
        self.closed.emit()

    def _slide(self, x0: int, x1: int, curve, ms: int = 200) -> None:
        self._anim.stop()
        self._anim.setDuration(ms)
        self._anim.setEasingCurve(curve)
        self._anim.setStartValue(QPoint(x0, 0))
        self._anim.setEndValue(QPoint(x1, 0))
        self._anim.start()

    def _on_anim_done(self) -> None:
        if not self.is_open:
            self.hide()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.close_panel()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # soft shadow strip on the left edge (painted, no QGraphicsEffect)
        g = QLinearGradient(0, 0, SHADOW, 0)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 90))
        p.fillRect(0, 0, SHADOW, self.height(), g)
        panel = QRectF(SHADOW, -14, self.width() - SHADOW + 14, self.height() + 28)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor("#222224"))
        p.drawRoundedRect(panel, 14, 14)
