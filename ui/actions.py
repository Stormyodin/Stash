"""Launch / open-folder / uninstall helpers. Every function returns an error string or None."""
from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

from core.models import AppEntry

log = logging.getLogger("stash.actions")
WIN = sys.platform == "win32"


def target_path(e: AppEntry) -> str:
    return e.exe_path or e.install_path or e.launcher


def launch(e: AppEntry) -> str | None:
    try:
        if e.launcher and "://" in e.launcher:
            if not QDesktopServices.openUrl(QUrl(e.launcher)):
                return f"No handler for {e.launcher.split(':', 1)[0]}://"
            return None
        exe = e.exe_path
        if not exe or not os.path.exists(exe):
            return "Executable not found — try rescanning"
        cwd = os.path.dirname(exe) or None
        if WIN:
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            try:
                subprocess.Popen([exe], cwd=cwd, creationflags=flags, close_fds=True)
            except OSError as exc:
                if getattr(exc, "winerror", None) == 740:  # requires elevation -> let the shell prompt UAC
                    os.startfile(exe)  # type: ignore[attr-defined]
                else:
                    raise
        else:
            subprocess.Popen([exe], cwd=cwd, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return None
    except Exception as exc:
        log.warning("launch failed: %s", exc)
        return f"Couldn't launch: {exc}"


def open_folder(e: AppEntry) -> str | None:
    folder = e.install_path or (os.path.dirname(e.exe_path) if e.exe_path else "")
    if not folder or not os.path.isdir(folder):
        return "Folder not found"
    if WIN and e.exe_path and os.path.isfile(e.exe_path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(e.exe_path)])
        return None
    return None if QDesktopServices.openUrl(QUrl.fromLocalFile(folder)) else "Couldn't open folder"


def copy_path(e: AppEntry) -> str:
    path = target_path(e)
    QGuiApplication.clipboard().setText(path)
    return path


def _registry_uninstall_string(e: AppEntry) -> str:
    import winreg

    want_name = e.name.casefold()
    want_dir = os.path.normcase(os.path.normpath(e.install_path)) if e.install_path else ""
    key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as k:
                            def val(n):
                                try:
                                    return str(winreg.QueryValueEx(k, n)[0])
                                except OSError:
                                    return ""
                            name = val("DisplayName").casefold()
                            loc = val("InstallLocation")
                            loc = os.path.normcase(os.path.normpath(loc.strip('"'))) if loc else ""
                            if name == want_name or (want_dir and loc == want_dir):
                                cmd = val("UninstallString")
                                if cmd:
                                    return cmd
                    except OSError:
                        continue
    return ""


def _shell_run(cmd: str) -> None:
    """Run an UninstallString via ShellExecute so UAC elevation prompts work."""
    import ctypes

    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        exe, args = cmd[1:end], cmd[end + 1:].strip()
    else:
        low = cmd.lower()
        cut = low.find(".exe")
        cut = cut + 4 if cut >= 0 else len(cmd)
        exe, args = cmd[:cut], cmd[cut:].strip()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", exe, args or None, None, 1)
    if rc <= 32:
        raise OSError(f"ShellExecute failed ({rc})")


def uninstall(e: AppEntry) -> str | None:
    if not WIN:
        return "Uninstall is available on Windows only"
    try:
        for t in e.tags:
            if t.startswith("appid:"):
                QDesktopServices.openUrl(QUrl(f"steam://uninstall/{t[6:]}"))
                return None
        cmd = _registry_uninstall_string(e)
        if cmd:
            _shell_run(cmd)
            return None
        QDesktopServices.openUrl(QUrl("ms-settings:appsfeatures"))
        return "No uninstaller registered — opened Apps & Features"
    except Exception as exc:
        log.warning("uninstall failed: %s", exc)
        return f"Couldn't start uninstaller: {exc}"
