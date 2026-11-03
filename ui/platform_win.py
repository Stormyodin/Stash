"""Windows-only niceties: Win11 rounded corners + dark frame, AppUserModelID, global hotkey. No-ops elsewhere."""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

log = logging.getLogger("stash.platform")
WIN = sys.platform == "win32"


def set_app_id(app_id: str = "Stash.AppLibrary") -> None:
    if WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass


def style_window(hwnd: int) -> None:
    """Rounded corners (DWMWA_WINDOW_CORNER_PREFERENCE=33 -> ROUND) and dark mode (20) on Windows 11."""
    if not WIN:
        return
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        for attr, value in ((33, 2), (20, 1)):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception as exc:
        log.debug("DWM styling unavailable: %s", exc)


_MODS = {"ctrl": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, owner: "GlobalHotkey") -> None:
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        o = self.owner
        et = event_type.data() if hasattr(event_type, "data") else event_type
        if isinstance(et, str):
            et = et.encode()
        if o.registered and et in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == o.id:
                    o.activated.emit()
                    return True, 0
            except Exception:
                pass
        return False, 0


class GlobalHotkey(QObject):
    """System-wide hotkey via RegisterHotKey; emits ``activated`` even when Stash is unfocused/hidden.
    Install ``hotkey.filter`` with QCoreApplication.installNativeEventFilter()."""
    activated = Signal()

    def __init__(self, sequence: str = "Ctrl+K", hotkey_id: int = 0x5354) -> None:
        super().__init__()
        self.filter = _HotkeyFilter(self)
        self.sequence = sequence
        self.id = hotkey_id
        self.hwnd = 0
        self.registered = False

    def register(self, hwnd: int) -> bool:
        if not WIN:
            return False
        import ctypes
        parts = [p.strip().lower() for p in self.sequence.split("+")]
        mods = MOD_NOREPEAT
        vk = 0
        for p in parts:
            if p in _MODS:
                mods |= _MODS[p]
            elif len(p) == 1:
                vk = ord(p.upper())
            elif p.startswith("f") and p[1:].isdigit():
                vk = 0x70 + int(p[1:]) - 1
        if not vk:
            return False
        self.hwnd = hwnd
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(ctypes.c_void_p(hwnd), self.id, mods, vk))
        if not self.registered:
            log.warning("global hotkey %s is taken by another app", self.sequence)
        return self.registered

    def unregister(self) -> None:
        if WIN and self.registered:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(ctypes.c_void_p(self.hwnd), self.id)
            self.registered = False


def bring_to_front(hwnd: int) -> None:
    """Windows refuses SetForegroundWindow from background processes unless we briefly attach input."""
    if not WIN:
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        u.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        fg = u.GetForegroundWindow()
        cur = ctypes.windll.kernel32.GetCurrentThreadId()
        other = u.GetWindowThreadProcessId(fg, None)
        u.AttachThreadInput(other, cur, True)
        u.SetForegroundWindow(ctypes.c_void_p(hwnd))
        u.AttachThreadInput(other, cur, False)
    except Exception:
        pass
