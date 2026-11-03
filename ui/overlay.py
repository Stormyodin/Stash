"""First-run full-window scan overlay: big progress ring, ticking source names, live count."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .widgets import Ring, TrafficLights

DISPLAY = {"Filesystem": "Portable apps", "StartMenu": "Start Menu", "Registry": "Installed programs"}


def display_name(src: str) -> str:
    return DISPLAY.get(src, src)


class _Chip(QWidget):
    """Rounded status pill, custom-painted (pending / active / done)."""
    STATES = {
        "pending": (theme.TEXT2, QColor(255, 255, 255, 13), ""),
        "active": (theme.TEXT, QColor(10, 132, 255, 56), ""),
        "done": (theme.SUCCESS, QColor(50, 215, 75, 31), "✓ "),
    }

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.state = "pending"
        self.f = theme.font(11, QFont.Medium)
        from PySide6.QtGui import QFontMetrics
        self.setFixedSize(QFontMetrics(self.f).horizontalAdvance("✓ " + label) + 24, 22)

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def is_done(self) -> bool:
        return self.state == "done"

    def paintEvent(self, e) -> None:
        fg, bg, mark = self.STATES[self.state]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 11, 11)
        p.setFont(self.f)
        p.setPen(QColor(fg))
        p.drawText(self.rect(), Qt.AlignCenter, mark + self.label)


class ScanOverlay(QWidget):
    finished = Signal()

    def __init__(self, source_names: list[str], parent: QWidget) -> None:
        super().__init__(parent)
        self.sources = source_names
        self.hide()
        self.lights = TrafficLights(self)
        self.lights.move(16, 14)

        lay = QVBoxLayout(self)
        lay.addStretch(3)
        self.ring = Ring(96, 5.0)
        lay.addWidget(self.ring, 0, Qt.AlignHCenter)
        lay.addSpacing(26)
        title = QLabel("Finding your apps")
        title.setFont(theme.font(22, QFont.DemiBold))
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        lay.addSpacing(6)
        self.source_lbl = QLabel("Preparing…")
        self.source_lbl.setStyleSheet(f"color:{theme.TEXT2};font-size:13px;")
        self.source_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.source_lbl)
        lay.addSpacing(18)
        self.count_lbl = QLabel("0")
        self.count_lbl.setFont(theme.font(40, QFont.Light))
        self.count_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.count_lbl)
        sub = QLabel("apps found")
        sub.setProperty("role", "secondary")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(24)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch()
        self.chips: dict[str, _Chip] = {}
        for s in source_names:
            c = _Chip(display_name(s))
            chips.addWidget(c)
            self.chips[s] = c
        chips.addStretch()
        lay.addLayout(chips)
        lay.addStretch(4)

        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)
        self._fade = QPropertyAnimation(self._fx, b"opacity", self)
        self._fade.setDuration(320)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._faded)
        self._done = 0

    def start(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self._done = 0
        for c in self.chips.values():
            c.set_state("pending")
        if self.sources:
            self.chips[self.sources[0]].set_state("active")
            self.source_lbl.setText(f"Scanning {display_name(self.sources[0])}…")
        self.count_lbl.setText("0")
        self._fade.stop()
        self._fx.setOpacity(1.0)
        self.raise_()
        self.show()
        self.ring.start()

    def on_progress(self, source: str, total: int) -> None:
        if source in self.chips:
            self.chips[source].set_state("done")
        self._done = min(len(self.sources), self._done + 1)
        self.ring.set_progress(self._done / max(1, len(self.sources)))
        self.count_lbl.setText(f"{total:,}")
        nxt = next((s for s in self.sources if not self.chips[s].is_done()), None)
        if nxt:
            self.chips[nxt].set_state("active")
            self.source_lbl.setText(f"Scanning {display_name(nxt)}…")
        else:
            self.source_lbl.setText("Finishing up…")

    def finish(self) -> None:
        self.ring.set_progress(1.0)
        self.source_lbl.setText("Done")
        self._fade.stop()
        self._fade.setStartValue(self._fx.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _faded(self) -> None:
        if self._fx.opacity() <= 0.01:
            self.ring.stop()
            self.hide()
            self.finished.emit()

    def resizeEvent(self, e) -> None:
        self.lights.move(16, 14)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
        p.setRenderHint(QPainter.Antialiasing)
        # faint radial-ish accent glow behind the ring
        c = self.ring.geometry().center()
        r = 200
        g = QRadialGradient(QPointF(c), r)
        g.setColorAt(0.0, QColor(10, 132, 255, 46))
        g.setColorAt(1.0, QColor(10, 132, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
