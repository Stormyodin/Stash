"""Delegate-painted grid cards and list rows + the virtualized view hosting them.

Only visible items are ever painted and no QWidget exists per item, so 2000 apps cost a few
hundred KB (the entries themselves) plus a bounded icon LRU. All motion is QPropertyAnimation-driven.
"""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QModelIndex, QObject, QPoint, QPropertyAnimation, QRect, QRectF, QSize,
                            Qt, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyledItemDelegate

from . import theme
from .icons import IconCache, paint_placeholder
from .model import EntryRole, MatchRole, fmt_date, fmt_size

CARD_W, CARD_H = 160, 180
CELL_W, CELL_H = 176, 196
ROW_H = 48
STAGGER_MS, FADE_MS = 20, 180

C_CARD = QColor(theme.CARD)
C_CARD_HOVER = QColor(theme.CARD_HOVER)
C_BORDER = QColor(theme.BORDER)
C_TEXT = QColor(theme.TEXT)
C_TEXT2 = QColor(theme.TEXT2)
C_ACCENT = QColor(theme.ACCENT)
C_BG = QColor(theme.BG)
C_ALT = QColor(theme.ROW_ALT)
CAT_COLORS = {k: QColor(v) for k, v in theme.CATEGORY_COLORS.items()}


def lerp(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


class Animator(QObject):
    """A float property whose changes trigger a repaint callback; driven by QPropertyAnimation."""

    def __init__(self, on_change, parent=None) -> None:
        super().__init__(parent)
        self._v = 0.0
        self._cb = on_change

    def _get(self) -> float:
        return self._v

    def _set(self, v: float) -> None:
        self._v = v
        self._cb()

    value = Property(float, _get, _set)

    def animate(self, start: float, end: float, ms: int, curve=QEasingCurve.OutCubic) -> QPropertyAnimation:
        anim = getattr(self, "_anim", None)
        if anim is None:
            anim = self._anim = QPropertyAnimation(self, b"value", self)
        anim.stop()
        anim.setDuration(ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(curve)
        anim.start()
        return anim


class HoverTracker(QObject):
    """Animated hover-in for the current item and hover-out for the previous one (two animators total)."""

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        self.vp = viewport
        self.cur_id: str | None = None
        self.prev_id: str | None = None
        self.ms = 120
        self._in = Animator(viewport.update, self)
        self._out = Animator(viewport.update, self)

    def set_hover(self, app_id: str | None) -> None:
        if app_id == self.cur_id:
            return
        if self.cur_id is not None:
            self.prev_id = self.cur_id
            self._out.animate(self._in.value, 0.0, self.ms)
        self.cur_id = app_id
        if app_id is not None:
            self._in.animate(0.0, 1.0, self.ms)

    def progress(self, app_id: str) -> float:
        if app_id == self.cur_id:
            return self._in.value
        if app_id == self.prev_id:
            return self._out.value
        return 0.0


def draw_highlighted(p: QPainter, rect: QRect, text: str, idx: tuple[int, ...], color: QColor,
                     align=Qt.AlignLeft | Qt.AlignVCenter) -> None:
    fm = p.fontMetrics()
    shown = fm.elidedText(text, Qt.ElideRight, rect.width())
    if not idx:
        p.setPen(color)
        p.drawText(rect, align, shown)
        return
    hl = set(i for i in idx if i < len(shown) - (1 if shown.endswith("…") and shown != text else 0))
    x = rect.x()
    if align & Qt.AlignHCenter:
        x += (rect.width() - fm.horizontalAdvance(shown)) // 2
    base = rect.y() + (rect.height() + fm.ascent() - fm.descent()) // 2
    # draw contiguous runs to keep kerning mostly intact
    i = 0
    while i < len(shown):
        on = i in hl
        j = i
        while j < len(shown) and (j in hl) == on:
            j += 1
        run = shown[i:j]
        p.setPen(C_ACCENT if on else color)
        p.drawText(x, base, run)
        x += fm.horizontalAdvance(run)
        i = j


def draw_badge(p: QPainter, x: int, cy: int, text: str, color: QColor, font: QFont, right_align=False) -> int:
    fm = QFontMetrics(font)
    w = fm.horizontalAdvance(text) + 12
    h = 16
    if right_align:
        x -= w
    r = QRectF(x, cy - h / 2, w, h)
    bg = QColor(color)
    bg.setAlpha(46)
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(r, 8, 8)
    p.setFont(font)
    p.setPen(color.lighter(125))
    p.drawText(r, Qt.AlignCenter, text)
    return w


class _BaseDelegate(QStyledItemDelegate):
    def __init__(self, icons: IconCache, hover: HoverTracker, fade: Animator, view) -> None:
        super().__init__(view)
        self.icons = icons
        self.hover = hover
        self.fade = fade
        self.view = view
        self.selected_id: str | None = None
        self.f_name = theme.font(13, QFont.DemiBold)
        self.f_small = theme.font(11)
        self.f_badge = theme.font(10, QFont.DemiBold)

    def opacity(self, app_id: str) -> float:
        ranks = self.view.model().fade if self.view.model() is not None else None
        if not ranks:
            return 1.0
        rank = ranks.get(app_id)
        if rank is None:
            return 1.0
        return max(0.0, min(1.0, (self.fade.value - rank * STAGGER_MS) / FADE_MS))

    def paint_icon(self, p: QPainter, rect: QRectF, e) -> None:
        pm = self.icons.get(e)
        if pm is not None:
            p.drawPixmap(rect.toRect(), pm)
        else:
            paint_placeholder(p, rect, e.name, e.id)


class GridDelegate(_BaseDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(CELL_W, CELL_H)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        e = index.data(EntryRole)
        if e is None:
            return
        op = self.opacity(e.id)
        if op <= 0.0:
            return
        h = self.hover.progress(e.id)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(op)
        cell = option.rect
        card = QRectF(cell.x() + (cell.width() - CARD_W) / 2, cell.y() + (cell.height() - CARD_H) / 2 + (1 - op) * 8,
                      CARD_W, CARD_H)
        c = card.center()
        if h > 0:
            s = 1.0 + 0.03 * h
            p.translate(c)
            p.scale(s, s)
            p.translate(-c)
            # soft blue glow: a few expanding low-alpha rounded rects (much cheaper than a blur effect)
            p.setBrush(Qt.NoBrush)
            for grow, alpha in ((1.5, 70), (3.5, 34), (6.0, 14)):
                pen = QPen(QColor(10, 132, 255, int(alpha * h)), 2.0)
                p.setPen(pen)
                p.drawRoundedRect(card.adjusted(-grow, -grow, grow, grow), 12 + grow, 12 + grow)
        selected = e.id == self.selected_id
        border = C_ACCENT if selected else lerp(C_BORDER, QColor(10, 132, 255, 150), h)
        p.setPen(QPen(border, 1.5 if selected else 1.0))
        p.setBrush(lerp(C_CARD, C_CARD_HOVER, h))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)

        top_h = CARD_H * 0.6
        icon = QRectF(c.x() - 32, card.y() + (top_h - 64) / 2 + 6, 64, 64)
        self.paint_icon(p, icon, e)

        # name
        p.setFont(self.f_name)
        name_rect = QRect(int(card.x() + 12), int(card.y() + top_h + 4), CARD_W - 24, 20)
        draw_highlighted(p, name_rect, e.name, index.data(MatchRole), C_TEXT, Qt.AlignHCenter | Qt.AlignVCenter)
        # badge + size
        cy = int(card.y() + top_h + 40)
        draw_badge(p, int(card.x() + 12), cy, e.category.value, CAT_COLORS.get(e.category, C_TEXT2), self.f_badge)
        p.setFont(self.f_small)
        p.setPen(C_TEXT2)
        p.drawText(QRect(int(card.x() + 12), cy - 9, CARD_W - 24, 18), Qt.AlignRight | Qt.AlignVCenter,
                   fmt_size(e.size_bytes))
        p.restore()


class ListDelegate(_BaseDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(max(320, self.view.viewport().width()), ROW_H)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        e = index.data(EntryRole)
        if e is None:
            return
        op = self.opacity(e.id)
        if op <= 0.0:
            return
        h = self.hover.progress(e.id)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(op)
        r = QRectF(option.rect).adjusted(8, 1, -8, -1)
        base = C_BG if index.row() % 2 == 0 else C_ALT
        bg = lerp(base, C_CARD, h)
        p.setPen(QPen(C_ACCENT, 1.2) if e.id == self.selected_id else Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)

        x = int(r.x()) + 12
        cy = int(r.center().y())
        self.paint_icon(p, QRectF(x, cy - 16, 32, 32), e)
        x += 44
        right_w = 300
        text_w = max(60, int(r.right()) - x - right_w - 12)
        p.setFont(self.f_name)
        draw_highlighted(p, QRect(x, cy - 17, text_w, 18), e.name, index.data(MatchRole), C_TEXT)
        p.setFont(self.f_small)
        p.setPen(C_TEXT2)
        sub = e.publisher or (e.install_path or e.exe_path or e.launcher)
        p.drawText(QRect(x, cy + 1, text_w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.ElideMiddle, text_w))
        # right-hand columns: size | badge | date
        rx = int(r.right()) - 12
        p.drawText(QRect(rx - 96, cy - 9, 96, 18), Qt.AlignRight | Qt.AlignVCenter, fmt_date(e.install_date))
        draw_badge(p, rx - 110, cy, e.category.value, CAT_COLORS.get(e.category, C_TEXT2), self.f_badge,
                   right_align=True)
        p.setFont(self.f_small)
        p.setPen(C_TEXT2)
        p.drawText(QRect(rx - 300, cy - 9, 90, 18), Qt.AlignRight | Qt.AlignVCenter, fmt_size(e.size_bytes))
        p.restore()


class AppView(QListView):
    """Virtualized grid/list view with animated hover, staggered fades and smooth wheel scrolling."""
    entryClicked = Signal(object)
    entryActivated = Signal(object)
    entryContext = Signal(object, object)  # entry, global pos
    emptyClicked = Signal()

    def __init__(self, icons: IconCache, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFrameShape(QListView.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, False)
        self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.hover = HoverTracker(self.viewport(), self)
        self.fade = Animator(self.viewport().update, self)
        self.fade.value = 1e9
        self.fade.animate(1e9, 1e9, 0).finished.connect(self._fade_done)  # create anim once, connect once
        self.grid_delegate = GridDelegate(icons, self.hover, self.fade, self)
        self.list_delegate = ListDelegate(icons, self.hover, self.fade, self)
        icons.ready.connect(lambda _id: self.viewport().update())
        self._scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(240)
        self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_target = 0
        self.mode = ""
        self.set_mode("grid")

    # ---- modes ------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        if mode == "grid":
            self.setItemDelegate(self.grid_delegate)
            self.setViewMode(QListView.IconMode)
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(QListView.Adjust)
            self.setMovement(QListView.Static)
            self.setSpacing(0)
            self.hover.ms = 120
            self.setViewportMargins(8, 8, 8, 8)
            self._fit_grid()
        else:
            self.setItemDelegate(self.list_delegate)
            self.setViewMode(QListView.ListMode)
            self.setFlow(QListView.TopToBottom)
            self.setWrapping(False)
            self.setGridSize(QSize())
            self.setSpacing(0)
            self.hover.ms = 80
            self.setViewportMargins(0, 6, 0, 6)
        self.doItemsLayout()

    def set_selected(self, app_id: str | None) -> None:
        self.grid_delegate.selected_id = self.list_delegate.selected_id = app_id
        self.viewport().update()

    def _fit_grid(self) -> None:
        """Stretch the grid cell so columns fill the width evenly (centered, Finder-like)."""
        if self.mode != "grid":
            return
        w = self.viewport().width() - 16  # IconMode wraps early if cells exactly fill the width
        cols = max(1, w // CELL_W)
        cell = QSize(max(CELL_W, w // cols - 1), CELL_H)
        if cell != self.gridSize():
            self.setGridSize(cell)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self.mode == "grid":
            self._fit_grid()
        else:
            self.scheduleDelayedItemsLayout()  # rows track the viewport width

    # ---- animations -------------------------------------------------------
    def stagger_in(self, ids: list[str]) -> None:
        """Fade the given ids in, STAGGER_MS apart (one animation drives all of them)."""
        model = self.model()
        if model is None or not ids:
            return
        model.fade = {i: n for n, i in enumerate(ids)}
        total = (len(ids) - 1) * STAGGER_MS + FADE_MS
        self.fade.animate(0.0, float(total), total, QEasingCurve.Linear)

    def _fade_done(self) -> None:
        if self.model() is not None:
            self.model().fade = {}
        self.viewport().update()

    def visible_ids(self, limit: int = 80) -> list[str]:
        model = self.model()
        out = []
        if model is None:
            return out
        vr = self.viewport().rect()
        first = self.indexAt(vr.topLeft() + QPoint(4, 4))
        start = first.row() if first.isValid() else 0
        for row in range(start, min(model.rowCount(), start + limit)):
            if not self.visualRect(model.index(row)).intersects(vr):
                if out:
                    break
                continue
            out.append(model.entry(row).id)
        return out

    # ---- input ------------------------------------------------------------
    def wheelEvent(self, ev) -> None:
        if not ev.pixelDelta().isNull() or ev.angleDelta().y() == 0:  # touchpads are already smooth
            super().wheelEvent(ev)
            return
        sb = self.verticalScrollBar()
        if self._scroll_anim.state() != QPropertyAnimation.Running:
            self._scroll_target = sb.value()
        step = ev.angleDelta().y() / 120 * (CELL_H * 0.6 if self.mode == "grid" else ROW_H * 2.5)
        self._scroll_target = max(sb.minimum(), min(sb.maximum(), int(self._scroll_target - step)))
        self._scroll_anim.stop()
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(self._scroll_target)
        self._scroll_anim.start()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        idx = self.indexAt(ev.position().toPoint())
        e = idx.data(EntryRole) if idx.isValid() else None
        self.hover.set_hover(e.id if e else None)
        self.viewport().setCursor(Qt.PointingHandCursor if e else Qt.ArrowCursor)
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev) -> None:
        self.hover.set_hover(None)
        super().leaveEvent(ev)

    def mousePressEvent(self, ev) -> None:
        idx = self.indexAt(ev.position().toPoint())
        e = idx.data(EntryRole) if idx.isValid() else None
        if ev.button() == Qt.LeftButton:
            if e is not None:
                self.entryClicked.emit(e)
            else:
                self.emptyClicked.emit()
        elif ev.button() == Qt.RightButton and e is not None:
            self.entryContext.emit(e, ev.globalPosition().toPoint())
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:
        idx = self.indexAt(ev.position().toPoint())
        if idx.isValid() and ev.button() == Qt.LeftButton:
            self.entryActivated.emit(idx.data(EntryRole))
        ev.accept()
