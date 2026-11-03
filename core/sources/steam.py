"""Steam libraries: libraryfolders.vdf + appmanifest_*.acf."""
from __future__ import annotations

import os
import re
import sys

from ..models import AppEntry, Source
from ._common import IS_WIN, from_epoch, largest_exe

NAME = "Steam"
# Redistributables / runtimes that are not user-facing games.
_SKIP_APPIDS = {"228980", "1070560", "1391110", "1628350", "1493710", "1826330", "2180100"}
_SKIP_NAME = re.compile(r"^(proton|steam linux runtime|steamworks common)", re.I)


def _load_vdf(path: str) -> dict:
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    try:
        import vdf
        return vdf.loads(text)
    except ImportError:
        return _mini_vdf(text)


def _mini_vdf(text: str) -> dict:
    """Minimal KeyValues parser used when the `vdf` package is unavailable."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack, key = [root], None
    for quoted, brace in tokens:
        if brace == "{":
            new: dict = {}
            stack[-1][key] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        elif key is None:
            key = quoted
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return root


def find_steam_root() -> str:
    override = os.environ.get("STASH_STEAM_PATH")
    if override:
        return override if os.path.isdir(override) else ""
    candidates: list[str] = []
    if IS_WIN:
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for v in ("SteamPath", "InstallPath"):
                            try:
                                candidates.append(winreg.QueryValueEx(k, v)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        candidates.append(r"C:\Program Files (x86)\Steam")
    else:
        home = os.path.expanduser("~")
        candidates += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                       os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "steamapps")):
            return os.path.normpath(c)
    return ""


def library_paths(root: str) -> list[str]:
    paths = [root]
    vdf_path = os.path.join(root, "steamapps", "libraryfolders.vdf")
    if os.path.isfile(vdf_path):
        try:
            data = _load_vdf(vdf_path)
            lf = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for k, v in lf.items():
                p = v.get("path") if isinstance(v, dict) else (v if k.isdigit() else None)
                if p:
                    paths.append(p)
        except (OSError, ValueError, SyntaxError):
            pass
    out, seen = [], set()
    for p in paths:
        n = os.path.normcase(os.path.normpath(p))
        if n not in seen and os.path.isdir(os.path.join(p, "steamapps")):
            seen.add(n)
            out.append(os.path.normpath(p))
    return out


def scan() -> list[AppEntry]:
    root = find_steam_root()
    if not root:
        return []
    out: list[AppEntry] = []
    for lib in library_paths(root):
        apps_dir = os.path.join(lib, "steamapps")
        try:
            manifests = [de.path for de in os.scandir(apps_dir)
                         if de.name.startswith("appmanifest_") and de.name.endswith(".acf")]
        except OSError:
            continue
        for mf in manifests:
            try:
                st = _load_vdf(mf).get("AppState") or {}
            except (OSError, ValueError, SyntaxError):
                continue
            appid, name = str(st.get("appid", "")), st.get("name", "")
            if not appid or not name or appid in _SKIP_APPIDS or _SKIP_NAME.match(name):
                continue
            install = os.path.join(apps_dir, "common", st.get("installdir", ""))
            exe = largest_exe(install, 2) if IS_WIN and os.path.isdir(install) else ""
            out.append(AppEntry(
                name=name, exe_path=exe, install_path=install, icon_path=exe,
                size_bytes=int(st.get("SizeOnDisk", 0) or 0),
                version=str(st.get("buildid", "")), publisher="",
                install_date=from_epoch(st.get("LastUpdated")),
                last_used=from_epoch(st.get("LastPlayed")),
                source=Source.STEAM, launcher=f"steam://rungameid/{appid}",
                tags=["steam", f"appid:{appid}"],
            ))
    return out
