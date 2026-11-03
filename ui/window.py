"""Stash main window: frameless macOS-style shell wiring the scanner core to the views."""
from __future__ import annotations

import gc
import logging

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QStackedLayout, QSystemTrayIcon, QVBoxLayout, QWidget)

from core import ScanBusyError, StashScanner, sources
from core.models import ScanDiff

from . import actions, platform_win, theme
from .delegates import AppView
from .details import DetailsPanel
from .icons import IconCache, draw_logo
from .model import SECTIONS, SORTS, AppModel, fmt_ago
from .overlay import ScanOverlay, display_name
from .palette import CommandPalette
from .widgets import RescanButton, SearchField, SectionList, SegmentedToggle, Toast, TrafficLights

log = logging.getLogger("stash.ui")
SOURCE_NAMES = [m.NAME for m in sources.PRIORITY_SOURCES] + [sources.FALLBACK_SOURCE.NAME]
GRIP = 5


class ScanBridge(QObject):
    """Marshals scanner worker-thread callbacks onto the UI thread (queued signals)."""
    progress = Signal(str, int)
    full_done = Signal(object)
    diff_done = Signal(object)
    failed = Signal(str)


class _DragArea(QWidget):
    """Empty space that moves the frameless window (and double-click zooms).

    The system move starts only once the mouse actually travels: starting it on press lets the native
    move loop swallow the click, which breaks double-click-to-restore on Windows.
    """
    _press = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        w = self.window()
        if self._press is None or not (e.buttons() & Qt.LeftButton) or w.isFullScreen():
            return
        gp = e.globalPosition().toPoint()
        if (gp - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        if hasattr(w, "restore_under_cursor"):
            w.restore_under_cursor(gp)
        if w.windowHandle():
            w.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e) -> None:
        self._press = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self._press = None
        if e.button() == Qt.LeftButton and hasattr(self.window(), "toggle_maximize"):
            self.window().toggle_maximize()


class _Grip(QWidget):
    """Invisible resize handle on a window edge/corner (frameless windows have none)."""
    CURSORS = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor, Qt.TopEdge: Qt.SizeVerCursor,
               Qt.BottomEdge: Qt.SizeVerCursor}

    def __init__(self, edges, parent) -> None:
        super().__init__(parent)
        self.edges = edges
        if edges in self.CURSORS:
            self.setCursor(self.CURSORS[edges])
        elif edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeBDiagCursor)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and not self.window().isMaximized() and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)


class MainWindow(QWidget):
    def __init__(self, scanner: StashScanner | None = None) -> None:
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setObjectName("Root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Stash")
        self.setWindowIcon(QIcon(draw_logo(256)))
        self.setMinimumSize(860, 560)
        self.setFocusPolicy(Qt.StrongFocus)
        self.settings = QSettings("Stash", "Stash")
        self.scanner = scanner or StashScanner()
        self.bridge = ScanBridge()
        self.icons = IconCache(64, capacity=384)
        self.big_icons = IconCache(96, capacity=8, threads=1)
        self.model = AppModel(self)
        self._quitting = False
        self._first_show = True
        self._scan_kind = ""
        self._sources_done = 0
        self._normal_geom: QRect | None = None   # set while zoomed (our own maximize; respects the taskbar)
        self._fs_restore: QRect | None = None    # geometry to return to when leaving F11 fullscreen
        self._pending_uninstall: dict[str, int] = {}  # entry id -> refreshes left before giving up
        self._left_for_uninstaller = False

        self._build_ui()
        self._build_overlays()
        self._wire()
        self._restore_settings()
        self._build_tray()

    # ================================================================ UI construction
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sidebar
        sb = QWidget()
        sb.setObjectName("Sidebar")
        sb.setAttribute(Qt.WA_StyledBackground, True)
        sb.setFixedWidth(220)
        sl = QVBoxLayout(sb)
        sl.setContentsMargins(0, 0, 0, 14)
        sl.setSpacing(0)
        head = _DragArea()
        head.setFixedHeight(44)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 0, 0, 0)
        self.lights = TrafficLights()
        hl.addWidget(self.lights)
        hl.addStretch()
        sl.addWidget(head)
        brand = _DragArea()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(18, 4, 16, 14)
        bl.setSpacing(10)
        logo = QLabel()
        lp = draw_logo(int(30 * self.devicePixelRatioF()))
        lp.setDevicePixelRatio(self.devicePixelRatioF())
        logo.setPixmap(lp)
        bl.addWidget(logo)
        word = QLabel("Stash")
        word.setFont(theme.font(19, QFont.Bold))
        bl.addWidget(word)
        bl.addStretch()
        sl.addWidget(brand)
        lib = QLabel("LIBRARY")
        lib.setProperty("role", "section")
        lib.setContentsMargins(22, 4, 0, 6)
        sl.addWidget(lib)
        self.sections = SectionList(SECTIONS)
        sl.addWidget(self.sections)
        sl.addStretch()
        self.search = SearchField("Search")
        sw = QWidget()
        swl = QVBoxLayout(sw)
        swl.setContentsMargins(12, 0, 12, 10)
        swl.addWidget(self.search)
        sl.addWidget(sw)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(14, 0, 12, 0)
        bottom.setSpacing(8)
        self.rescan_btn = RescanButton()
        bottom.addWidget(self.rescan_btn)
        info = QVBoxLayout()
        info.setSpacing(0)
        self.rescan_title = QLabel("Rescan")
        self.rescan_title.setFont(theme.font(12, QFont.DemiBold))
        self.last_scan_lbl = QLabel("Never scanned")
        self.last_scan_lbl.setProperty("role", "secondary")
        info.addWidget(self.rescan_title)
        info.addWidget(self.last_scan_lbl)
        bottom.addLayout(info)
        bottom.addStretch()
        sl.addLayout(bottom)
        root.addWidget(sb)

        # ---- main area
        self.main = QWidget()
        self.main.setObjectName("Main")
        self.main.setAttribute(Qt.WA_StyledBackground, True)
        ml = QVBoxLayout(self.main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = _DragArea()
        top.setFixedHeight(64)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(24, 10, 20, 4)
        tl.setSpacing(10)
        tbox = QVBoxLayout()
        tbox.setSpacing(0)
        self.title_lbl = QLabel("All")
        self.title_lbl.setProperty("role", "title")
        self.count_lbl = QLabel("0 items")
        self.count_lbl.setProperty("role", "secondary")
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.count_lbl)
        tl.addLayout(tbox)
        tl.addStretch()
        sort_lbl = QLabel("Sort")
        sort_lbl.setProperty("role", "secondary")
        tl.addWidget(sort_lbl)
        self.sort_box = QComboBox()
        self.sort_box.addItems(SORTS)
        self.sort_box.setCursor(Qt.PointingHandCursor)
        self.sort_box.setFixedSize(150, 28)
        tl.addWidget(self.sort_box)
        self.toggle = SegmentedToggle([("grid", "grid"), ("list", "list")])
        tl.addWidget(self.toggle)
        ml.addWidget(top)

        self.content = QWidget()
        self.stack = QStackedLayout(self.content)
        self.view = AppView(self.icons)
        self.view.setModel(self.model)
        self.stack.addWidget(self.view)
        self.empty_lbl = QLabel()
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet(f"color:{theme.TEXT2};font-size:14px;")
        self.stack.addWidget(self.empty_lbl)
        ml.addWidget(self.content, 1)

        self.status = QLabel("Ready")
        self.status.setFixedHeight(26)
        self.status.setContentsMargins(24, 0, 24, 0)
        self.status.setStyleSheet(f"color:{theme.TEXT2};font-size:11px;border-top:1px solid #2A2A2C;")
        ml.addWidget(self.status)
        root.addWidget(self.main, 1)

    def _build_overlays(self) -> None:
        self.details = DetailsPanel(self.big_icons, self.main)
        self.crossfade = QLabel(self.content)
        self.crossfade.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.crossfade.hide()
        self._xfx = QGraphicsOpacityEffect(self.crossfade)
        self.crossfade.setGraphicsEffect(self._xfx)
        self._xanim = QPropertyAnimation(self._xfx, b"opacity", self)
        self._xanim.setDuration(150)
        self._xanim.setStartValue(1.0)
        self._xanim.setEndValue(0.0)
        self._xanim.setEasingCurve(QEasingCurve.OutCubic)
        self._xanim.finished.connect(lambda: (self.crossfade.hide(), self.crossfade.clear()))
        self.toast = Toast(self)
        self.palette = CommandPalette(self.icons, self.model.all_entries, self)
        self.overlay = ScanOverlay(SOURCE_NAMES, self)
        self.grips = [_Grip(e, self) for e in (
            Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge, Qt.TopEdge | Qt.LeftEdge,
            Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge)]

    def _wire(self) -> None:
        for lights in (self.lights, self.overlay.lights):
            lights.closeClicked.connect(self.close)
            lights.minimizeClicked.connect(self.showMinimized)
            lights.zoomClicked.connect(self.toggle_maximize)
        self.sections.sectionChanged.connect(self._on_section)
        self.sort_box.currentTextChanged.connect(self._on_sort)
        self.toggle.changed.connect(self._on_mode)
        self._search_timer = QTimer(self, singleShot=True, interval=70)
        self._search_timer.timeout.connect(lambda: self._apply_view(query=self.search.text()))
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.returnPressed.connect(self._launch_first)
        self.rescan_btn.clicked.connect(self.rescan)
        self.view.entryClicked.connect(self._on_entry_clicked)
        self.view.entryActivated.connect(self._launch)
        self.view.entryContext.connect(self._context_menu)
        self.view.emptyClicked.connect(self.details.close_panel)
        self.details.closed.connect(lambda: self.view.set_selected(None))
        self.details.launchRequested.connect(self._launch)
        self.details.folderRequested.connect(self._open_folder)
        self.details.copyRequested.connect(self._copy_path)
        self.details.uninstallRequested.connect(self._uninstall)
        self.palette.launchRequested.connect(self._launch)
        self.palette.revealRequested.connect(self.reveal)
        self.overlay.finished.connect(lambda: self.view.stagger_in(self.view.visible_ids()))
        self.bridge.progress.connect(self._on_progress)
        self.bridge.full_done.connect(self._on_full_done)
        self.bridge.diff_done.connect(self._on_diff_done)
        self.bridge.failed.connect(self._on_scan_failed)
        self.model.modelReset.connect(self._update_counts)
        self.model.rowsInserted.connect(self._update_counts)
        self.model.rowsRemoved.connect(self._update_counts)

        QShortcut(QKeySequence("Ctrl+K"), self, self.palette.toggle)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("F5"), self, self.rescan)
        QShortcut(QKeySequence("Ctrl+R"), self, self.rescan)
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self._set_mode("grid"))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self._set_mode("list"))
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._escape)
        QShortcut(QKeySequence(Qt.Key_F11), self, self.toggle_fullscreen)

        self._ago_timer = QTimer(self, interval=60_000)
        self._ago_timer.timeout.connect(self._update_last_scan)
        self._ago_timer.start()

        self.hotkey = platform_win.GlobalHotkey(self.settings.value("global_hotkey", "Ctrl+K", str))
        QApplication.instance().installNativeEventFilter(self.hotkey.filter)
        self.hotkey.activated.connect(self._global_palette)

    def _build_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(draw_logo(64)), self)
        self.tray.setToolTip("Stash")
        menu = QMenu()
        menu.addAction("Open Stash", self.show_and_raise)
        menu.addAction("Command Palette", self._global_palette)
        menu.addAction("Rescan", self.rescan)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_and_raise() if r in (QSystemTrayIcon.Trigger,
                                                                             QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    # ================================================================ settings
    def _restore_settings(self) -> None:
        # Only the *normal* rect is stored; fullscreen is never restored (reopens zoomed instead).
        rect = self.settings.value("normal_geometry")
        if not isinstance(rect, QRect):
            rect = None
            old = self.settings.value("geometry")      # legacy saveGeometry() blob could carry max/fullscreen
            if old is not None:
                self.restoreGeometry(old)
                self.setWindowState(Qt.WindowNoState)
                rect = self.normalGeometry() if self.normalGeometry().isValid() else self.geometry()
                self.settings.remove("geometry")
        scr = (QApplication.screenAt(rect.center()) if rect is not None else None) or QApplication.primaryScreen()
        avail = scr.availableGeometry() if scr else QRect(0, 0, 1180, 760)
        if rect is None or rect.width() < 200 or rect.height() < 200:
            rect = QRect(0, 0, 1180, 760)
            rect.moveCenter(avail.center())
        rect.setSize(rect.size().boundedTo(avail.size()).expandedTo(self.minimumSize()))
        if not avail.intersects(rect):                 # monitor unplugged etc.
            rect.moveCenter(avail.center())
        self.setGeometry(rect)
        if self.settings.value("window_state", "normal", str) == "maximized":
            self._normal_geom = QRect(rect)
            self.setMinimumSize(self.minimumSize().boundedTo(avail.size()))
            self.setGeometry(avail)
        mode = self.settings.value("view_mode", "grid", str)
        sort = self.settings.value("sort", "Name", str)
        if sort in SORTS:
            self.sort_box.blockSignals(True)
            self.sort_box.setCurrentText(sort)
            self.sort_box.blockSignals(False)
            self.model.sort = sort
        self._set_mode(mode if mode in ("grid", "list") else "grid", animate=False)

    def _save_settings(self) -> None:
        fs = self.isFullScreen()
        if self._normal_geom is not None:
            normal = self._normal_geom
        elif fs and self._fs_restore is not None:
            normal = self._fs_restore
        elif self.isMaximized() or fs:
            normal = self.normalGeometry()
        else:
            normal = self.geometry()
        self.settings.setValue("normal_geometry", QRect(normal))
        self.settings.setValue("window_state", "maximized" if (fs or self.is_zoomed() or self.isMaximized())
                               else "normal")
        self.settings.setValue("view_mode", self.view.mode)
        self.settings.setValue("sort", self.model.sort)

    # ================================================================ data flow
    def load_initial(self) -> None:
        """Populate from cache instantly; first-run triggers a full scan with the overlay."""
        try:
            entries = self.scanner.get_cached()
        except Exception:
            log.exception("cache read failed")
            entries = []
        self.model.set_entries(entries)
        self._update_last_scan()
        self.status.setText(f"Ready · {len(entries):,} apps from cache" if entries else "Ready")
        if not entries:
            self._start_full_scan()

    def _start_full_scan(self) -> None:
        try:
            self._begin_scan("full")
            self.overlay.start()
            self.scanner.start_scan(self.bridge.progress.emit, self.bridge.full_done.emit,
                                    error_cb=lambda exc: self.bridge.failed.emit(str(exc)))
        except ScanBusyError:
            pass

    def rescan(self) -> None:
        if self.scanner.is_scanning:
            self.toast.show_message("A scan is already running")
            return
        try:
            self._begin_scan("diff")
            self.scanner.rescan(self.bridge.progress.emit, self.bridge.diff_done.emit,
                                error_cb=lambda exc: self.bridge.failed.emit(str(exc)))
        except ScanBusyError:
            self.toast.show_message("A scan is already running")

    def _begin_scan(self, kind: str) -> None:
        self._scan_kind = kind
        self._sources_done = 0
        self.rescan_btn.start()
        self.rescan_title.setText("Scanning…")
        self.status.setText(f"Scanning {display_name(SOURCE_NAMES[0])}…")

    def _on_progress(self, source: str, total: int) -> None:
        self._sources_done += 1
        frac = self._sources_done / len(SOURCE_NAMES)
        self.rescan_btn.set_progress(frac)
        nxt = SOURCE_NAMES[self._sources_done] if self._sources_done < len(SOURCE_NAMES) else None
        self.status.setText(f"Scanning {display_name(nxt)}… {total:,} found" if nxt
                            else f"Finishing up… {total:,} found")
        if self.overlay.isVisible():
            self.overlay.on_progress(source, total)

    def _end_scan(self) -> None:
        self.rescan_btn.stop()
        self.rescan_title.setText("Rescan")
        self._update_last_scan()
        errs = self.scanner.last_errors
        dur = self.scanner.last_duration
        msg = f"Ready · {self.model.total():,} apps · scanned in {dur:.1f}s"
        if errs:
            msg += f" · {len(errs)} source(s) failed: {', '.join(errs)}"
        self.status.setText(msg)

    def _on_full_done(self, entries) -> None:
        self.model.set_entries(entries)
        self._end_scan()
        if self.overlay.isVisible():
            self.overlay.finish()  # its fade-out triggers the staggered card reveal
        else:
            self.view.stagger_in(self.view.visible_ids())

    def _on_diff_done(self, diff: ScanDiff) -> None:
        removed_names = [self.model.get(i).name for i in diff.removed
                         if i in self._pending_uninstall and self.model.get(i)]
        for i in diff.removed:
            self._pending_uninstall.pop(i, None)
        added = self.model.apply_diff(diff)
        self._end_scan()
        for e in diff.updated:
            self.icons.invalidate(e.id)
        if self.details.is_open and self.details.entry:
            if self.details.entry.id in diff.removed:
                self.details.close_panel()
            else:
                fresh = self.model.get(self.details.entry.id)
                if fresh:
                    self.details.set_entry(fresh)
        if added:
            self.view.stagger_in(added[:80])
        parts = []
        if diff.added:
            parts.append(f"{len(diff.added)} new")
        if diff.updated:
            parts.append(f"{len(diff.updated)} updated")
        if diff.removed:
            parts.append(f"{len(diff.removed)} removed")
        if removed_names:
            self.toast.show_message(f"Uninstalled {removed_names[0]}" if len(removed_names) == 1
                                    else f"Uninstalled {len(removed_names)} apps")
        else:
            self.toast.show_message(" · ".join(parts) if parts else "Everything is up to date")

    def _on_scan_failed(self, err: str) -> None:
        self._end_scan()
        self.status.setText(f"Scan failed: {err}")
        if self.overlay.isVisible():
            self.overlay.finish()
        self.toast.show_message("Scan failed — see status bar")

    def _update_last_scan(self) -> None:
        try:
            t = self.scanner.cache.last_scan_time()
        except Exception:
            t = None
        self.last_scan_lbl.setText(f"Scanned {fmt_ago(t)}" if t else "Never scanned")

    def _update_counts(self, *_a) -> None:
        self.sections.set_counts(self.model.counts)
        n = self.model.rowCount()
        total = self.model.counts.get(self.model.section, 0)
        self.count_lbl.setText(f"{n:,} of {total:,} items" if self.model.query else f"{n:,} item{'s' * (n != 1)}")
        if n == 0:
            if self.model.query:
                self.empty_lbl.setText(f"No matches for “{self.search.text()}”")
            elif self.scanner.is_scanning:
                self.empty_lbl.setText("Scanning…")
            else:
                self.empty_lbl.setText("Nothing here yet")
            self.stack.setCurrentWidget(self.empty_lbl)
        else:
            self.stack.setCurrentWidget(self.view)

    # ================================================================ view changes
    def _apply_view(self, crossfade: bool = False, **kw) -> None:
        if crossfade and self.view.isVisible() and self.model.rowCount():
            self.crossfade.setGeometry(self.view.geometry())
            self.crossfade.setPixmap(self.view.grab())
            self._xfx.setOpacity(1.0)
            self.crossfade.show()
            self.crossfade.raise_()
            self._xanim.stop()
            self._xanim.start()
        self.model.set_view(**kw)
        self.view.scrollToTop()

    def _on_section(self, key: str) -> None:
        self.title_lbl.setText(dict((k, l) for k, l, _ in SECTIONS)[key])
        self.details.close_panel()
        self._apply_view(crossfade=True, section=key)

    def _on_sort(self, sort: str) -> None:
        self._apply_view(crossfade=True, sort=sort)

    def _on_mode(self, mode: str) -> None:
        self._set_mode(mode)

    def _set_mode(self, mode: str, animate: bool = True) -> None:
        if animate and self.view.isVisible() and self.model.rowCount():
            self.crossfade.setGeometry(self.view.geometry())
            self.crossfade.setPixmap(self.view.grab())
            self._xfx.setOpacity(1.0)
            self.crossfade.show()
            self.crossfade.raise_()
            self._xanim.start()
        self.toggle.set_current(mode, animate)
        self.view.set_mode(mode)

    def reveal(self, e) -> None:
        """Show an entry in the main view (from the palette)."""
        self.sections.select("all")
        if self.search.text():
            self.search.clear()
            self._apply_view(query="")
        row = self.model.row_of(e.id)
        if row >= 0:
            self.view.scrollTo(self.model.index(row), AppView.PositionAtCenter)
        self._on_entry_clicked(e)

    # ================================================================ actions
    def _on_entry_clicked(self, e) -> None:
        self.view.set_selected(e.id)
        self.details.open_for(e)

    def _launch_first(self) -> None:
        e = self.model.entry(0)
        if e:
            self._launch(e)

    def _launch(self, e) -> None:
        err = actions.launch(e)
        self.toast.show_message(err or f"Launching {e.name}…")

    def _open_folder(self, e) -> None:
        err = actions.open_folder(e)
        if err:
            self.toast.show_message(err)

    def _copy_path(self, e) -> None:
        actions.copy_path(e)
        self.toast.show_message("Path copied to clipboard")

    def _uninstall(self, e) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Uninstall")
        box.setText(f"Uninstall {e.name}?")
        box.setInformativeText("Stash will start this app's own uninstaller.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.button(QMessageBox.Yes).setText("Uninstall")
        box.button(QMessageBox.Yes).setProperty("kind", "danger")
        if box.exec() == QMessageBox.Yes:
            err = actions.uninstall(e)
            if err is None or err.startswith("No uninstaller registered"):
                # Refresh once the user comes back to Stash (uninstallers run in their own window and often
                # re-spawn from %TEMP%, so waiting on the process is unreliable). Event-driven, no polling.
                self._pending_uninstall[e.id] = 3
                self._left_for_uninstaller = False     # armed by the next focus loss (uninstaller/UAC window)
            self.toast.show_message(err or f"Started uninstaller for {e.name} — Stash will refresh when it's done")

    def _check_pending_uninstall(self) -> None:
        if not self._pending_uninstall:
            return
        if not self.isActiveWindow():
            self._left_for_uninstaller = True      # focus went to the uninstaller (or elsewhere)
            return
        if self._left_for_uninstaller and not self.scanner.is_scanning:
            self._left_for_uninstaller = False
            for k in list(self._pending_uninstall):     # give up after a few refreshes (uninstall cancelled)
                self._pending_uninstall[k] -= 1
                if self._pending_uninstall[k] <= 0:
                    del self._pending_uninstall[k]
            self.rescan()

    def _context_menu(self, e, pos) -> None:
        m = QMenu(self)
        m.addAction("Launch", lambda: self._launch(e))
        m.addAction("Show Details", lambda: self._on_entry_clicked(e))
        m.addSeparator()
        m.addAction("Open Folder", lambda: self._open_folder(e))
        m.addAction("Copy Path", lambda: self._copy_path(e))
        m.addSeparator()
        m.addAction("Uninstall…", lambda: self._uninstall(e))
        m.exec(pos)

    def _escape(self) -> None:
        if self.palette.is_open:
            self.palette.close_palette()
        elif self.details.is_open:
            self.details.close_panel()
        elif self.isFullScreen():
            self.toggle_fullscreen()
        elif self.search.text():
            self.search.clear()

    def _global_palette(self) -> None:
        self.show_and_raise()
        if not self.palette.is_open:
            QTimer.singleShot(30, self.palette.open_palette)

    # ================================================================ window chrome
    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        platform_win.bring_to_front(int(self.winId()))

    def is_zoomed(self) -> bool:
        return self._normal_geom is not None and not self.isFullScreen()

    def toggle_maximize(self) -> None:
        """Green button / title double-click: normal <-> zoomed. Zoom is done by hand to the screen's
        availableGeometry: a native maximize of a frameless window on Windows covers the taskbar and its
        state can desync after a system move, leaving showNormal() with nothing to restore."""
        if self.isFullScreen():
            self.toggle_fullscreen()
            return
        if self.isMaximized():                         # native maximize (e.g. Win+Up)
            self.showNormal()
            return
        if self._normal_geom is not None:
            g, self._normal_geom = self._normal_geom, None
            self.setGeometry(g)
            return
        scr = self.screen() or QApplication.primaryScreen()
        if scr:
            self._normal_geom = self.geometry()
            avail = scr.availableGeometry()
            self.setMinimumSize(self.minimumSize().boundedTo(avail.size()))  # tiny/high-DPI screens
            self.setGeometry(avail)

    def toggle_fullscreen(self) -> None:
        """F11 toggles true fullscreen; Esc / F11 / green button leave it."""
        if self.isFullScreen():
            self.showNormal()
            if self._fs_restore is not None:
                self.setGeometry(self._fs_restore)
            self._fs_restore = None
        else:
            self._fs_restore = self.geometry()
            self.showFullScreen()

    def restore_under_cursor(self, gp) -> None:
        """Dragging the title bar of a zoomed window restores it with the cursor at the same relative x."""
        if self.isMaximized():
            self.showNormal()
        if self._normal_geom is None:
            return
        g, self._normal_geom = QRect(self._normal_geom), None
        cur = self.geometry()
        fx = (gp.x() - cur.x()) / max(1, cur.width())
        g.moveTo(gp.x() - int(g.width() * fx), gp.y() - min(gp.y() - cur.y(), 22))
        self.setGeometry(g)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._first_show:
            self._first_show = False
            hwnd = int(self.winId())
            platform_win.style_window(hwnd)
            self.setFocus()
            self.hotkey.register(hwnd)
            if self.model.rowCount() and not self.overlay.isVisible():
                QTimer.singleShot(0, lambda: self.view.stagger_in(self.view.visible_ids()))

    def changeEvent(self, e) -> None:
        if e.type() == e.Type.ActivationChange:
            self.lights.active = self.isActiveWindow()
            self.lights.update()
            self._check_pending_uninstall()
        super().changeEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        w, h, g = self.width(), self.height(), GRIP
        rects = [QRect(0, g, g, h - 2 * g), QRect(w - g, g, g, h - 2 * g), QRect(g, 0, w - 2 * g, g),
                 QRect(g, h - g, w - 2 * g, g), QRect(0, 0, g, g), QRect(w - g, 0, g, g), QRect(0, h - g, g, g),
                 QRect(w - g, h - g, g, g)]
        for grip, r in zip(self.grips, rects):
            grip.setGeometry(r)
            grip.raise_()
            grip.setVisible(not (self.isMaximized() or self.isFullScreen() or self.is_zoomed()))
        self.details.reposition()
        if self.palette.isVisible():
            self.palette.setGeometry(self.rect())
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.rect())

    def mousePressEvent(self, e) -> None:
        if self.details.is_open and not self.details.geometry().contains(self.main.mapFrom(self, e.position().toPoint())):
            self.details.close_panel()
        super().mousePressEvent(e)

    def closeEvent(self, e) -> None:
        self._save_settings()
        if self.tray is not None and not self._quitting and self.settings.value("close_to_tray", True, bool):
            e.ignore()
            self.hide()
            self._trim_memory()
            if not self.settings.value("tray_hint_shown", False, bool):
                self.tray.showMessage("Stash is still running", "Press Ctrl+K anywhere or use the tray icon.",
                                      QSystemTrayIcon.Information, 3000)
                self.settings.setValue("tray_hint_shown", True)
            return
        self._shutdown()
        e.accept()
        QApplication.instance().quit()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def _trim_memory(self) -> None:
        """While hidden in the tray, drop decoded icons (they reload from the disk cache)."""
        self.icons.clear()
        self.big_icons.clear()
        gc.collect()

    def _shutdown(self) -> None:
        self.hotkey.unregister()
        if self.tray:
            self.tray.hide()
        try:
            self.scanner.close()
        except Exception:
            pass

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.BG))
