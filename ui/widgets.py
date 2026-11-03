"""Small custom-painted widgets: traffic lights, sidebar sections, ring spinner, segmented toggle, toast."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSequentialAnimationGroup,
                            QSize, Qt, Signal)
from PySide6.QtGui import QColor, QConicalGradient, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QLineEdit, QWidget

from . import theme
from .icons import draw_glyph


def _anim(target, prop: bytes, ms: int, curve=QEasingCurve.OutCubic, parent=None) -> QPropertyAnimation:
    a = QPropertyAnimation(target, prop, parent or target)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    return a


# --------------------------------------------------------------------------- traffic lights
class TrafficLights(QWidget):
    closeClicked = Signal()
    minimizeClicked = Signal()
    zoomClicked = Signal()
    COLORS = ("#FF5F57", "#FEBC2E", "#28C840")
    D, GAP = 12, 8

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(3 * self.D + 2 * self.GAP + 4, self.D + 8)
        self.setMouseTracking(True)
        self._hover = False
        self._pressed = -1
        self.active = True

    def _hit(self, pos) -> int:
        for i in range(3):
            cx = 2 + i * (self.D + self.GAP) + self.D / 2
            if (pos.x() - cx) ** 2 + (pos.y() - self.height() / 2) ** 2 <= (self.D / 2 + 2) ** 2:
                return i
        return -1

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:
        self._pressed = self._hit(e.position())
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        hit = self._hit(e.position())
        if hit == self._pressed and hit >= 0:
            (self.closeClicked, self.minimizeClicked, self.zoomClicked)[hit].emit()
        self._pressed = -1
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        for i, col in enumerate(self.COLORS):
            x = 2 + i * (self.D + self.GAP)
            c = QColor(col) if (self.active or self._hover) else QColor("#4A4A4C")
            if i == self._pressed:
                c = c.darker(125)
            p.setPen(QPen(c.darker(130), 0.6))
            p.setBrush(c)
            p.drawEllipse(QRectF(x, cy - self.D / 2, self.D, self.D))
            if self._hover:
                pen = QPen(QColor(0, 0, 0, 150), 1.3)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                cx = x + self.D / 2
                k = 2.6
                if i == 0:
                    p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
                    p.drawLine(QPointF(cx + k, cy - k), QPointF(cx - k, cy + k))
                elif i == 1:
                    p.drawLine(QPointF(cx - k - 0.6, cy), QPointF(cx + k + 0.6, cy))
                else:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, 150))
                    tri = QPainterPath()
                    tri.moveTo(cx - 3, cy - 3)
                    tri.lineTo(cx + 1.6, cy - 3)
                    tri.lineTo(cx - 3, cy + 1.6)
                    tri.closeSubpath()
                    tri.moveTo(cx + 3, cy + 3)
                    tri.lineTo(cx - 1.6, cy + 3)
                    tri.lineTo(cx + 3, cy - 1.6)
                    tri.closeSubpath()
                    p.drawPath(tri)


# --------------------------------------------------------------------------- sidebar sections
class SectionList(QWidget):
    """Custom-painted sidebar list with an animated sliding accent pill."""
    sectionChanged = Signal(str)
    ITEM_H = 32

    def __init__(self, sections: list[tuple[str, str, object]], parent=None) -> None:
        super().__init__(parent)
        self.sections = [(k, label) for k, label, _ in sections]
        self.counts: dict[str, int] = {}
        self.current = 0
        self._hover = -1
        self._pill_y = 0.0
        self.setMouseTracking(True)
        self.setFixedHeight(len(self.sections) * self.ITEM_H + 4)
        self.setCursor(Qt.PointingHandCursor)
        self._pill_anim = _anim(self, b"pillY", 220)
        self.f = theme.font(13)
        self.f_sel = theme.font(13, QFont.DemiBold)
        self.f_count = theme.font(11)
        self._dot_colors = [QColor(theme.TEXT2), QColor(theme.CATEGORY_COLORS[_cat("Games")]),
                            QColor(theme.CATEGORY_COLORS[_cat("Apps")]), QColor(theme.CATEGORY_COLORS[_cat("DevTools")]),
                            QColor(theme.CATEGORY_COLORS[_cat("Media")]), QColor(theme.CATEGORY_COLORS[_cat("Portable")]),
                            QColor(theme.CATEGORY_COLORS[_cat("Other")])]

    def _get_pill(self) -> float:
        return self._pill_y

    def _set_pill(self, v: float) -> None:
        self._pill_y = v
        self.update()

    pillY = Property(float, _get_pill, _set_pill)

    def set_counts(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.update()

    def select(self, key: str, animate: bool = True) -> None:
        for i, (k, _) in enumerate(self.sections):
            if k == key:
                self._select(i, animate)
                return

    def _select(self, i: int, animate: bool = True) -> None:
        changed = i != self.current
        self.current = i
        target = float(2 + i * self.ITEM_H)
        if animate:
            self._pill_anim.stop()
            self._pill_anim.setStartValue(self._pill_y)
            self._pill_anim.setEndValue(target)
            self._pill_anim.start()
        else:
            self._set_pill(target)
        if changed:
            self.sectionChanged.emit(self.sections[i][0])

    def mouseMoveEvent(self, e) -> None:
        h = int((e.position().y() - 2) // self.ITEM_H)
        h = h if 0 <= h < len(self.sections) else -1
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        if self._hover >= 0:
            self._select(self._hover)

    def showEvent(self, e) -> None:
        self._set_pill(float(2 + self.current * self.ITEM_H))

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        if 0 <= self._hover != self.current:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(QRectF(10, 2 + self._hover * self.ITEM_H, w - 20, self.ITEM_H - 2), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(10, self._pill_y, w - 20, self.ITEM_H - 2), 8, 8)
        # which row is (mostly) under the pill -> white text
        under = int(round((self._pill_y - 2) / self.ITEM_H))
        for i, (k, label) in enumerate(self.sections):
            y = 2 + i * self.ITEM_H
            sel = i == under
            p.setPen(Qt.NoPen)
            dot = QColor(255, 255, 255) if sel else self._dot_colors[i % len(self._dot_colors)]
            p.setBrush(dot)
            p.drawRoundedRect(QRectF(22, y + (self.ITEM_H - 2) / 2 - 4, 8, 8), 2.5, 2.5)
            p.setFont(self.f_sel if sel else self.f)
            p.setPen(QColor(255, 255, 255) if sel else QColor(theme.TEXT))
            p.drawText(QRectF(40, y, w - 100, self.ITEM_H - 2), Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setFont(self.f_count)
            p.setPen(QColor(255, 255, 255, 210) if sel else QColor(theme.TEXT2))
            p.drawText(QRectF(w - 80, y, 58, self.ITEM_H - 2), Qt.AlignVCenter | Qt.AlignRight,
                       str(self.counts.get(k, 0)))


def _cat(v: str):
    from core.models import Category
    return Category(v)


# --------------------------------------------------------------------------- ring spinner
class Ring(QWidget):
    """Radial progress ring: determinate arc + rotating indeterminate comet, all property-animated."""

    def __init__(self, size: int = 34, thickness: float = 2.5, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.thickness = thickness
        self._angle = 0.0
        self._progress = 0.0
        self.spinning = False
        self._spin = _anim(self, b"angle", 900, QEasingCurve.Linear)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setLoopCount(-1)
        self._prog_anim = _anim(self, b"progress", 300)

    def _ga(self) -> float:
        return self._angle

    def _sa(self, v: float) -> None:
        self._angle = v
        self.update()

    angle = Property(float, _ga, _sa)

    def _gp(self) -> float:
        return self._progress

    def _sp(self, v: float) -> None:
        self._progress = v
        self.update()

    progress = Property(float, _gp, _sp)

    def start(self) -> None:
        self.spinning = True
        self._sp(0.0)
        self._spin.start()

    def stop(self) -> None:
        self.spinning = False
        self._spin.stop()
        self.update()

    def set_progress(self, frac: float) -> None:
        self._prog_anim.stop()
        self._prog_anim.setStartValue(self._progress)
        self._prog_anim.setEndValue(max(0.0, min(1.0, frac)))
        self._prog_anim.start()

    def ring_rect(self) -> QRectF:
        t = self.thickness
        return QRectF(t / 2 + 1, t / 2 + 1, self.width() - t - 2, self.height() - t - 2)

    def paint_ring(self, p: QPainter) -> None:
        if not self.spinning:
            return
        r = self.ring_rect()
        pen = QPen(QColor(255, 255, 255, 30), self.thickness)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        pen.setCapStyle(Qt.RoundCap)
        if self._progress > 0.001:
            pen.setColor(QColor(theme.ACCENT))
            p.setPen(pen)
            p.drawArc(r, 90 * 16, int(-self._progress * 360 * 16))
        grad = QConicalGradient(r.center(), -self._angle)
        grad.setColorAt(0.0, QColor(100, 180, 255, 255))
        grad.setColorAt(0.25, QColor(10, 132, 255, 0))
        grad.setColorAt(1.0, QColor(10, 132, 255, 0))
        pen.setBrush(grad)
        p.setPen(pen)
        p.drawArc(r, int(-self._angle * 16), 80 * 16)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_ring(p)


class RescanButton(Ring):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(34, 2.5, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Rescan (F5)")
        self._hover = False

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()) and not self.spinning:
            self.clicked.emit()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 34 if self._hover else 18))
        p.drawEllipse(QRectF(3, 3, self.width() - 6, self.height() - 6))
        # refresh glyph (rotates with the spinner)
        c = QPointF(self.width() / 2, self.height() / 2)
        p.save()
        p.translate(c)
        if self.spinning:
            p.rotate(self._angle)
        pen = QPen(QColor(theme.TEXT), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        rr = 6.0
        p.drawArc(QRectF(-rr, -rr, 2 * rr, 2 * rr), 60 * 16, 290 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TEXT))
        head = QPainterPath()
        head.moveTo(rr * 0.5 + 3.2, -rr * 0.87 + 0.2)
        head.lineTo(rr * 0.5 - 1.6, -rr * 0.87 - 3.2)
        head.lineTo(rr * 0.5 - 1.2, -rr * 0.87 + 2.6)
        head.closeSubpath()
        p.drawPath(head)
        p.restore()
        self.paint_ring(p)


# --------------------------------------------------------------------------- segmented toggle
class SegmentedToggle(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.options = options  # (key, glyph kind)
        self.seg_w = 34
        self.setFixedSize(self.seg_w * len(options) + 4, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.current = 0
        self._x = 2.0
        self._anim = _anim(self, b"knobX", 160)
        self._glyphs = {k: (draw_glyph(g, 14, QColor(theme.TEXT)), draw_glyph(g, 14, QColor(theme.TEXT2)))
                        for k, g in options}

    def _gx(self) -> float:
        return self._x

    def _sx(self, v: float) -> None:
        self._x = v
        self.update()

    knobX = Property(float, _gx, _sx)

    def set_current(self, key: str, animate=True) -> None:
        for i, (k, _) in enumerate(self.options):
            if k == key:
                self.current = i
                end = 2.0 + i * self.seg_w
                if animate:
                    self._anim.stop()
                    self._anim.setStartValue(self._x)
                    self._anim.setEndValue(end)
                    self._anim.start()
                else:
                    self._sx(end)

    def mousePressEvent(self, e) -> None:
        i = int((e.position().x() - 2) // self.seg_w)
        if 0 <= i < len(self.options) and i != self.current:
            self.set_current(self.options[i][0])
            self.changed.emit(self.options[i][0])

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(self._x, 2, self.seg_w, self.height() - 4), 6, 6)
        for i, (k, _) in enumerate(self.options):
            pm = self._glyphs[k][0 if i == self.current else 1]
            x = 2 + i * self.seg_w + (self.seg_w - 14) / 2
            p.drawPixmap(QPointF(x, (self.height() - 14) / 2), pm)


# --------------------------------------------------------------------------- search field
class SearchField(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.addAction(QIcon(draw_glyph("search", 14, QColor(theme.TEXT2))), QLineEdit.LeadingPosition)
        self.setFixedHeight(32)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.clear()
            self.clearFocus()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- toast
class Toast(QLabel):
    """Bottom-centered transient message: fade in, hold, fade out (one animation group)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background: rgba(44,44,46,0.96); border: 1px solid {theme.BORDER}; border-radius: 10px;"
                           f" padding: 8px 16px; color: {theme.TEXT};")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._group = QSequentialAnimationGroup(self)
        fade_in = _anim(self._fx, b"opacity", 160, parent=self._group)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_out = _anim(self._fx, b"opacity", 260, QEasingCurve.InCubic, parent=self._group)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        self._group.addAnimation(fade_in)
        self._group.addPause(1600)
        self._group.addAnimation(fade_out)
        self._group.finished.connect(self.hide)
        self.hide()

    def show_message(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 48)
        self.raise_()
        self.show()
        self._group.stop()
        self._group.start()

    def sizeHint(self) -> QSize:
        return super().sizeHint()
