"""Xbox app / Microsoft Store games (C:/XboxGames, WindowsApps)."""
from __future__ import annotations

import os
import string
import sys
import xml.etree.ElementTree as ET

from ..models import AppEntry, Source
from ._common import IS_WIN, dir_size, file_mtime

NAME = "Xbox"
_FRAMEWORK_HINTS = ("framework", "vclibs", ".net.", "ui.xaml", "runtime", "directx", "_neutral_")


def _drives() -> list[str]:
    if not IS_WIN:
        return []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]
    except Exception:
        return ["C:\\"]


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_game_config(path: str) -> dict:
    """Pull name/version/publisher/exe out of a MicrosoftGame.config."""
    info: dict = {}
    for _, el in ET.iterparse(path, events=("start",)):
        tag = _strip_ns(el.tag)
        if tag == "Identity":
            info.setdefault("version", el.get("Version", ""))
            info.setdefault("identity", el.get("Name", ""))
        elif tag == "ShellVisuals":
            info.setdefault("name", el.get("DefaultDisplayName", ""))
            info.setdefault("publisher", el.get("PublisherDisplayName", ""))
            logo = el.get("Square150x150Logo") or el.get("Square44x44Logo")
            if logo:
                info.setdefault("logo", logo)
        elif tag == "Executable" and "exe" not in info:
            info["exe"] = el.get("Name", "")
    return info


def _entry_from_config(cfg_path: str, root: str) -> AppEntry | None:
    try:
        info = parse_game_config(cfg_path)
    except (ET.ParseError, OSError):
        return None
    content = os.path.dirname(cfg_path)
    name = info.get("name") or info.get("identity") or os.path.basename(root)
    if name.startswith("ms-resource:"):
        name = os.path.basename(root)
    exe = os.path.join(content, info["exe"]) if info.get("exe") else ""
    logo = os.path.join(content, info["logo"]) if info.get("logo") else exe
    return AppEntry(
        name=name, exe_path=exe, install_path=root, icon_path=logo,
        size_bytes=dir_size(root, max_depth=4, max_entries=20_000), version=info.get("version", ""),
        publisher=info.get("publisher", ""), install_date=file_mtime(cfg_path),
        source=Source.XBOX, launcher="", tags=["xbox"],
    )


def _scan_xboxgames(base: str) -> list[AppEntry]:
    out: list[AppEntry] = []
    try:
        with os.scandir(base) as it:
            dirs = [de.path for de in it if de.is_dir()]
    except OSError:
        return out
    for d in dirs:
        for cfg in (os.path.join(d, "Content", "MicrosoftGame.config"), os.path.join(d, "MicrosoftGame.config")):
            if os.path.isfile(cfg):
                e = _entry_from_config(cfg, d)
                if e:
                    out.append(e)
                break
    return out


def _scan_windowsapps(base: str) -> list[AppEntry]:
    """WindowsApps is ACL-protected; only packages we can read with a game config are used."""
    out: list[AppEntry] = []
    try:
        with os.scandir(base) as it:
            dirs = [de for de in it if de.is_dir()]
    except OSError:
        return out
    best: dict[str, os.DirEntry] = {}
    for de in dirs:
        low = de.name.lower()
        if any(h in low for h in _FRAMEWORK_HINTS):
            continue
        family = de.name.split("_")[0]
        if family not in best or de.name > best[family].name:
            best[family] = de
    for de in best.values():
        cfg = os.path.join(de.path, "MicrosoftGame.config")
        if os.path.isfile(cfg):
            e = _entry_from_config(cfg, de.path)
            if e:
                out.append(e)
    return out


def scan() -> list[AppEntry]:
    if sys.platform != "win32" and not os.environ.get("STASH_XBOX_PATH"):
        return []
    out: list[AppEntry] = []
    override = os.environ.get("STASH_XBOX_PATH")
    roots = [override] if override else [os.path.join(d, "XboxGames") for d in _drives()]
    for r in roots:
        if os.path.isdir(r):
            out.extend(_scan_xboxgames(r))
    if IS_WIN:
        pf = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles", r"C:\Program Files")
        out.extend(_scan_windowsapps(os.path.join(pf, "WindowsApps")))
    return out
