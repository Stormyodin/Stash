"""Targeted filesystem scan for programs not registered anywhere else.

Windows: Program Files, Program Files (x86), AppData/Local(/Programs) — one entry per
top-level app folder, using the largest .exe as the main executable.
Linux (testing): each executable in /usr/bin and /usr/local/bin is an entry.
Only directory metadata (os.scandir) is touched; file contents are never read.
"""
from __future__ import annotations

import os
import sys
from typing import Iterable

from ..models import AppEntry, Source, norm_path
from ._common import IS_WIN, file_mtime, is_exe, is_junk_exe

NAME = "Filesystem"

_SKIP_DIRS = {
    "common files", "windowsapps", "windows defender", "windows nt", "windows mail",
    "windows media player", "windows photo viewer", "windows portable devices",
    "windows security", "windows sidebar", "windowspowershell", "internet explorer",
    "microsoft.net", "reference assemblies", "msbuild", "modifiablewindowsapps",
    "temp", "packages", "microsoft", "crashdumps", "d3dscache", "cache", "caches",
    "installer", "package cache", "uninstall information", "dotnet", "nvidia corporation",
}
_EXE_DEPTH, _SIZE_DEPTH = 3, 5


def windows_roots() -> list[tuple[str, int]]:
    """(root, depth-of-app-folder) pairs."""
    e = os.environ.get
    roots = [e("ProgramW6432") or e("ProgramFiles"), e("ProgramFiles(x86)")]
    out = [(r, 1) for r in dict.fromkeys(filter(None, roots)) if os.path.isdir(r)]
    local = e("LOCALAPPDATA")
    if local:
        progs = os.path.join(local, "Programs")
        if os.path.isdir(progs):
            out.append((progs, 1))
        out.append((local, 1))
    return out


def _is_claimed(path: str, claimed: set[str]) -> bool:
    p = norm_path(path)
    for _ in range(8):
        if p in claimed:
            return True
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return False


def _summarise(folder: str) -> tuple[str, int]:
    """Walk ``folder`` once: (largest non-junk exe, approximate total size)."""
    best, best_size, total = "", -1, 0
    stack = [(folder, 0)]
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                for de in it:
                    try:
                        if de.is_dir(follow_symlinks=False):
                            if depth < _SIZE_DEPTH:
                                stack.append((de.path, depth + 1))
                            continue
                        size = de.stat(follow_symlinks=False).st_size
                        total += size
                        if depth <= _EXE_DEPTH and is_exe(de.name) and not is_junk_exe(de.name) and size > best_size:
                            best, best_size = de.path, size
                    except OSError:
                        continue
        except OSError:
            continue
    return best, total


def _scan_windows(claimed: set[str]) -> list[AppEntry]:
    out: list[AppEntry] = []
    roots = windows_roots()
    root_set = {norm_path(r) for r, _ in roots}
    for root, _depth in roots:
        try:
            with os.scandir(root) as it:
                folders = [de.path for de in it if de.is_dir(follow_symlinks=False)
                           and de.name.lower() not in _SKIP_DIRS]
        except OSError:
            continue
        for folder in folders:
            if norm_path(folder) in root_set or _is_claimed(folder, claimed):
                continue
            exe, size = _summarise(folder)
            if not exe or _is_claimed(exe, claimed):
                continue
            out.append(AppEntry(
                name=os.path.basename(folder), exe_path=exe, install_path=folder, icon_path=exe,
                size_bytes=size, install_date=file_mtime(folder), source=Source.PORTABLE,
                tags=["filesystem"],
            ))
    return out


def _scan_posix(claimed: set[str]) -> list[AppEntry]:
    out: list[AppEntry] = []
    roots = os.environ.get("STASH_FS_ROOTS", "/usr/bin:/usr/local/bin").split(os.pathsep)
    seen_real: set[str] = set()
    for root in roots:
        try:
            it = os.scandir(root)
        except OSError:
            continue
        with it:
            for de in it:
                try:
                    if not de.is_file() or not os.access(de.path, os.X_OK):
                        continue
                    real = os.path.realpath(de.path)
                    if real in seen_real or norm_path(de.path) in claimed:
                        continue
                    seen_real.add(real)
                    st = de.stat()
                except OSError:
                    continue
                out.append(AppEntry(
                    name=de.name, exe_path=de.path, install_path=root, icon_path="",
                    size_bytes=st.st_size, install_date=file_mtime(de.path),
                    source=Source.PORTABLE, tags=["filesystem"],
                ))
    return out


def scan(known_paths: Iterable[str] = ()) -> list[AppEntry]:
    """``known_paths``: install dirs / exe paths already found by other sources.

    If a ``set`` of already-normalised paths is passed it is used live (by reference),
    so paths claimed by other scanners running concurrently are skipped as they appear.
    """
    claimed = known_paths if isinstance(known_paths, set) else {norm_path(p) for p in known_paths if p}
    return _scan_windows(claimed) if IS_WIN else _scan_posix(claimed)
