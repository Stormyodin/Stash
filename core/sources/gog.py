"""GOG Galaxy: galaxy-2.0.db (read-only) with registry fallback."""
from __future__ import annotations

import os
import sqlite3
import sys

from ..models import AppEntry, Source
from ._common import IS_WIN, largest_exe

NAME = "GOG"


def db_path() -> str:
    override = os.environ.get("STASH_GOG_DB")
    if override:
        return override
    base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    return os.path.join(base, "GOG.com", "Galaxy", "storage", "galaxy-2.0.db")


def _from_db(path: str) -> list[AppEntry]:
    out: list[AppEntry] = []
    uri = "file:" + path.replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "InstalledBaseProducts" not in tables:
            return out
        has_ld = "LimitedDetails" in tables
        q = ("SELECT ib.productId, ib.installationPath, ld.title FROM InstalledBaseProducts ib "
             "LEFT JOIN LimitedDetails ld ON ld.productId = ib.productId") if has_ld else \
            "SELECT productId, installationPath, NULL FROM InstalledBaseProducts"
        for pid, ipath, title in con.execute(q):
            if not ipath:
                continue
            exe = largest_exe(ipath, 2) if IS_WIN and os.path.isdir(ipath) else ""
            out.append(AppEntry(
                name=title or os.path.basename(os.path.normpath(ipath)), exe_path=exe,
                install_path=os.path.normpath(ipath), icon_path=exe, publisher="GOG.com",
                source=Source.GOG, launcher=f"goggalaxy://openGameView/{pid}",
                tags=["gog", f"gogid:{pid}"],
            ))
    finally:
        con.close()
    return out


def _from_registry() -> list[AppEntry]:
    if sys.platform != "win32":
        return []
    import winreg
    out: list[AppEntry] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games")
    except OSError:
        return out
    with root:
        i = 0
        while True:
            try:
                gid = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, gid) as k:
                    def v(n):
                        try:
                            return winreg.QueryValueEx(k, n)[0]
                        except OSError:
                            return ""
                    name, path, exe = v("gameName"), v("path"), v("exe")
                    if name and path:
                        out.append(AppEntry(
                            name=name, exe_path=exe, install_path=path, icon_path=exe,
                            version=str(v("ver")), publisher="GOG.com", source=Source.GOG,
                            launcher=f"goggalaxy://openGameView/{gid}", tags=["gog", f"gogid:{gid}"],
                        ))
            except OSError:
                continue
    return out


def scan() -> list[AppEntry]:
    path = db_path()
    if os.path.isfile(path):
        try:
            entries = _from_db(path)
            if entries:
                return entries
        except sqlite3.Error:
            pass
    return _from_registry()
