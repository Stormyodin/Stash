"""Windows Uninstall registry keys (HKLM + HKCU, 64-bit and WOW6432Node)."""
from __future__ import annotations

import os
import sys

from ..models import AppEntry, Source
from ._common import is_exe, is_junk_exe, largest_exe, parse_yyyymmdd

NAME = "Registry"
UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def _val(key, name, default=None):
    import winreg
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def _icon_exe(display_icon: str) -> str:
    """'"C:\\x\\app.exe",0' -> 'C:\\x\\app.exe'."""
    if not display_icon:
        return ""
    path = display_icon.split(",")[0].strip().strip('"')
    return os.path.expandvars(path)


def _iter_keys():
    import winreg
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]
    for hive, view in hives:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view) as k:
                        yield sub, k
                except OSError:
                    continue


def scan() -> list[AppEntry]:
    if sys.platform != "win32":
        return []
    out: list[AppEntry] = []
    seen: set[str] = set()
    for subkey, k in _iter_keys():
        name = _val(k, "DisplayName")
        loc = (_val(k, "InstallLocation") or "").strip().strip('"')
        if not name or not loc:
            continue
        if _val(k, "SystemComponent") == 1 or _val(k, "ParentKeyName"):
            continue
        if str(_val(k, "ReleaseType", "")).lower() in ("update", "hotfix", "security update"):
            continue
        if not os.path.isdir(loc):
            continue
        icon = _icon_exe(_val(k, "DisplayIcon", ""))
        exe = icon if is_exe(icon) and not is_junk_exe(os.path.basename(icon)) and os.path.isfile(icon) else ""
        if not exe:
            exe = largest_exe(loc, max_depth=2)
        size_kb = _val(k, "EstimatedSize", 0)
        tags = []
        if subkey.startswith("Steam App "):
            tags.append("steam")
        e = AppEntry(
            name=str(name).strip(), exe_path=exe, install_path=loc,
            icon_path=icon if icon and os.path.isfile(icon) else exe,
            size_bytes=int(size_kb or 0) * 1024 if isinstance(size_kb, int) else 0,
            version=str(_val(k, "DisplayVersion", "") or ""),
            publisher=str(_val(k, "Publisher", "") or ""),
            install_date=parse_yyyymmdd(_val(k, "InstallDate")),
            source=Source.REGISTRY, tags=tags,
        )
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return out
