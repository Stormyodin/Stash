"""Async icon pipeline: disk cache -> extraction (Windows) -> bounded in-memory LRU of QPixmaps.

Never touches the disk or Win32 on the UI thread. Failed lookups fall back to a painted placeholder
(colored squircle + initials) so no memory is spent storing placeholder bitmaps.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPixmap)

from . import theme

log = logging.getLogger("stash.icons")

ICON_DIR = Path.home() / ".stash" / "icons"
DISK_PX = 128           # size stored on disk
IMAGE_EXT = {".png", ".ico", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
WIN_EXTRACT_EXT = {".exe", ".dll", ".ico", ".lnk", ".msc", ".cpl"}


# --------------------------------------------------------------------------- Windows extraction
def _extract_win(path: str, px: int):
    """Extract the primary icon of an exe/dll as a PIL RGBA image. Windows only; returns None on failure."""
    import ctypes
    from ctypes import wintypes as wt

    from PIL import Image

    user32, gdi32, shell32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.shell32
    HANDLE = ctypes.c_void_p
    user32.PrivateExtractIconsW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.POINTER(HANDLE), ctypes.POINTER(wt.UINT), wt.UINT, wt.UINT]
    user32.PrivateExtractIconsW.restype = wt.UINT
    user32.DestroyIcon.argtypes = [HANDLE]
    user32.GetDC.argtypes = [HANDLE]
    user32.GetDC.restype = HANDLE
    user32.ReleaseDC.argtypes = [HANDLE, HANDLE]
    user32.DrawIconEx.argtypes = [HANDLE, ctypes.c_int, ctypes.c_int, HANDLE, ctypes.c_int, ctypes.c_int,
                                  wt.UINT, HANDLE, wt.UINT]
    gdi32.CreateCompatibleDC.argtypes = [HANDLE]
    gdi32.CreateCompatibleDC.restype = HANDLE
    gdi32.SelectObject.argtypes = [HANDLE, HANDLE]
    gdi32.SelectObject.restype = HANDLE
    gdi32.DeleteObject.argtypes = [HANDLE]
    gdi32.DeleteDC.argtypes = [HANDLE]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    gdi32.CreateDIBSection.argtypes = [HANDLE, ctypes.POINTER(BITMAPINFOHEADER), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), HANDLE, wt.DWORD]
    gdi32.CreateDIBSection.restype = HANDLE

    hicon = HANDLE()
    icon_id = wt.UINT()
    got = user32.PrivateExtractIconsW(path, 0, px, px, ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0)
    if got in (0, 0xFFFFFFFF) or not hicon.value:
        # Fallback: shell association icon (e.g. generic exe icon)
        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [("hIcon", HANDLE), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
                        ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]
        shell32.SHGetFileInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(SHFILEINFOW), wt.UINT, wt.UINT]
        info = SHFILEINFOW()
        if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), 0x100) or not info.hIcon:
            return None
        hicon = HANDLE(info.hIcon)

    def render(flags: int) -> bytes:
        hdc_screen = user32.GetDC(None)
        hdc = gdi32.CreateCompatibleDC(hdc_screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), px, -px, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            old = gdi32.SelectObject(hdc, hbmp)
            user32.DrawIconEx(hdc, 0, 0, hicon, px, px, 0, None, flags)
            data = ctypes.string_at(bits, px * px * 4)
            gdi32.SelectObject(hdc, old)
            return data
        finally:
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc)
            user32.ReleaseDC(None, hdc_screen)

    try:
        color = render(0x0003)  # DI_NORMAL
        img = Image.frombuffer("RGBA", (px, px), color, "raw", "BGRA", 0, 1)
        if img.getchannel("A").getextrema()[1] == 0:  # legacy icon without alpha: use the AND mask
            mask = Image.frombuffer("RGBA", (px, px), render(0x0001), "raw", "BGRA", 0, 1).convert("L")
            img.putalpha(mask.point(lambda v: 255 if v < 128 else 0))
        return img.copy()
    finally:
        user32.DestroyIcon(hicon)


def _load_source(path: str, px: int):
    """Return a PIL image for an icon source path, or None."""
    from PIL import Image

    p = path.split(",")[0].strip().strip('"')
    if not p or not os.path.isfile(p):
        return None
    ext = os.path.splitext(p)[1].lower()
    if ext in IMAGE_EXT:
        with Image.open(p) as im:
            if ext == ".ico" and hasattr(im, "ico"):
                sizes = sorted(im.ico.sizes())
                best = next((s for s in sizes if s[0] >= px), sizes[-1]) if sizes else None
                if best:
                    im.size = best
            im.load()
            return im.convert("RGBA")
    if sys.platform == "win32" and ext in WIN_EXTRACT_EXT:
        return _extract_win(p, px)
    return None


def load_icon(app_id: str, sources: tuple[str, ...]) -> QImage | None:
    """Worker-thread icon resolution with disk cache. Returns a DISK_PX QImage or None."""
    disk = ICON_DIR / f"{app_id}.png"
    if disk.is_file():
        img = QImage(str(disk))
        return None if img.isNull() else img
    marker = ICON_DIR / f"{app_id}.none"
    if marker.exists():
        return None
    for src in sources:
        if not src:
            continue
        try:
            im = _load_source(src, DISK_PX)
        except Exception as exc:  # corrupt files, access denied, ...
            log.debug("icon load failed for %s: %s", src, exc)
            im = None
        if im is None:
            continue
        from PIL import Image
        if im.size != (DISK_PX, DISK_PX):
            im.thumbnail((DISK_PX, DISK_PX), Image.LANCZOS)
            canvas = Image.new("RGBA", (DISK_PX, DISK_PX), (0, 0, 0, 0))
            canvas.paste(im, ((DISK_PX - im.width) // 2, (DISK_PX - im.height) // 2))
            im = canvas
        try:
            ICON_DIR.mkdir(parents=True, exist_ok=True)
            im.save(disk, "PNG", optimize=False)
        except OSError:
            pass
        data = im.tobytes("raw", "RGBA")
        return QImage(data, DISK_PX, DISK_PX, DISK_PX * 4, QImage.Format_RGBA8888).copy()
    if sys.platform == "win32" and any(sources):
        try:  # remember failures so we don't re-extract on every launch
            ICON_DIR.mkdir(parents=True, exist_ok=True)
            marker.touch()
        except OSError:
            pass
    return None


# --------------------------------------------------------------------------- async cache
class _Runner(QRunnable):
    def __init__(self, cache: "IconCache") -> None:
        super().__init__()
        self.cache = cache

    def run(self) -> None:
        c = self.cache
        while True:
            with c._lock:
                if not c._stack:
                    c._active -= 1
                    return
                app_id, srcs = c._stack.pop()  # LIFO: most recently requested (visible) first
            img = None
            try:
                img = load_icon(app_id, srcs)
                if img is not None:
                    img = img.scaled(c._px_dev, c._px_dev, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                log.exception("icon worker error")
            c._loaded.emit(app_id, img)


class IconCache(QObject):
    """Bounded LRU of device-pixel-ratio aware pixmaps keyed by app id."""
    ready = Signal(str)
    _loaded = Signal(str, object)

    def __init__(self, logical_px: int = 64, capacity: int = 384, threads: int = 2, parent=None) -> None:
        super().__init__(parent)
        screen = QGuiApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio() if screen else 1.0
        self._px_dev = int(logical_px * self._dpr)
        self._cap = capacity
        self._mem: OrderedDict[str, QPixmap] = OrderedDict()
        self._failed: set[str] = set()
        self._queued: set[str] = set()
        self._stack: list[tuple[str, tuple[str, ...]]] = []
        self._lock = threading.Lock()
        self._active = 0
        self._threads = threads
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)
        self._pool.setExpiryTimeout(5000)  # idle threads die -> no idle RAM/CPU
        self._loaded.connect(self._on_loaded, Qt.QueuedConnection)

    def get(self, entry) -> QPixmap | None:
        pm = self._mem.get(entry.id)
        if pm is not None:
            self._mem.move_to_end(entry.id)
            return pm
        if entry.id not in self._failed:
            self._request(entry)
        return None

    def has_failed(self, app_id: str) -> bool:
        return app_id in self._failed

    def invalidate(self, app_id: str) -> None:
        self._mem.pop(app_id, None)
        self._failed.discard(app_id)

    def _request(self, entry) -> None:
        with self._lock:
            if entry.id in self._queued:
                return
            self._queued.add(entry.id)
            self._stack.append((entry.id, (entry.icon_path, entry.exe_path)))
            if len(self._stack) > 160:  # scrolled past: forget stale requests
                old_id, _ = self._stack.pop(0)
                self._queued.discard(old_id)
            spawn = self._active < self._threads
            if spawn:
                self._active += 1
        if spawn:
            self._pool.start(_Runner(self))

    def _on_loaded(self, app_id: str, img) -> None:
        self._queued.discard(app_id)
        if img is None:
            self._failed.add(app_id)
            return
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(self._dpr)
        self._mem[app_id] = pm
        while len(self._mem) > self._cap:
            self._mem.popitem(last=False)
        self.ready.emit(app_id)

    def clear(self) -> None:
        self._mem.clear()
        self._failed.clear()


# --------------------------------------------------------------------------- painting helpers
def _hue(seed: str) -> int:
    return int(hashlib.blake2b(seed.encode("utf-8", "surrogatepass"), digest_size=2).hexdigest(), 16) % 360


def initials(name: str) -> str:
    words = [w for w in "".join(c if c.isalnum() else " " for c in name).split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].capitalize()
    return (words[0][0] + words[1][0]).upper()


def squircle(rect: QRectF, radius_ratio: float = 0.225) -> QPainterPath:
    path = QPainterPath()
    r = min(rect.width(), rect.height()) * radius_ratio
    path.addRoundedRect(rect, r, r)
    return path


def paint_placeholder(p: QPainter, rect: QRectF, name: str, seed: str) -> None:
    """macOS-style gradient squircle with initials. Painted on demand, never cached."""
    h = _hue(seed)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor.fromHsl(h, 170, 120))
    grad.setColorAt(1.0, QColor.fromHsl((h + 32) % 360, 160, 72))
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawPath(squircle(rect))
    f = theme.font(max(9, int(rect.height() * 0.36)), QFont.DemiBold)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(rect, Qt.AlignCenter, initials(name))
    p.restore()


def draw_logo(size: int = 256) -> QPixmap:
    """The Stash app icon: blue squircle with three stacked layers."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor("#3FA2FF"))
    g.setColorAt(1, QColor("#0A5BD6"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(squircle(rect))
    cx, w, h = size / 2, size * 0.52, size * 0.15
    for i, alpha in enumerate((110, 170, 255)):
        y = size * 0.30 + i * size * 0.145
        layer = QPainterPath()
        layer.addRoundedRect(QRectF(cx - w / 2, y, w, h), h * 0.32, h * 0.32)
        p.setBrush(QColor(255, 255, 255, alpha))
        p.drawPath(layer)
    p.end()
    return pm


def draw_glyph(kind: str, size: int, color: QColor) -> QPixmap:
    """Small vector glyphs (no icon font / image assets needed)."""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = p.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.4, size / 11))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    s = size
    if kind == "grid":
        q = s * 0.36
        for x in (s * 0.1, s * 0.54):
            for y in (s * 0.1, s * 0.54):
                p.drawRoundedRect(QRectF(x, y, q, q), 2, 2)
    elif kind == "list":
        for y in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(s * 0.15, s * y), QPointF(s * 0.85, s * y))
    elif kind == "search":
        p.drawEllipse(QRectF(s * 0.12, s * 0.12, s * 0.56, s * 0.56))
        p.drawLine(QPointF(s * 0.6, s * 0.6), QPointF(s * 0.88, s * 0.88))
    elif kind == "close":
        p.drawLine(QPointF(s * 0.25, s * 0.25), QPointF(s * 0.75, s * 0.75))
        p.drawLine(QPointF(s * 0.75, s * 0.25), QPointF(s * 0.25, s * 0.75))
    p.end()
    return pm
