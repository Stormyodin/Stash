"""Shared helpers for source scanners (no file contents are ever read here)."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

IS_WIN = sys.platform == "win32"

# Executables that are never the "main" program of a folder.
_JUNK_EXE = re.compile(
    r"(^unins|uninst|setup|install|update|updater|crash|report|helper|redist|vc_?redist|"
    r"dxsetup|dotnet|repair|elevate|launcherpatcher|cefsharp|notification|bugsplat|"
    r"\.?vshost|squirrel|ue4prereq|createdump|service)", re.I)


def is_junk_exe(filename: str) -> bool:
    return bool(_JUNK_EXE.search(os.path.splitext(filename)[0]))


def is_exe(filename: str) -> bool:
    return filename.lower().endswith(".exe")


def largest_exe(root: str, max_depth: int = 2) -> str:
    """Return the largest non-junk .exe under ``root`` (bounded depth), or ''."""
    best, best_size = "", -1
    stack = [(root, 0)]
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                for de in it:
                    try:
                        if de.is_dir(follow_symlinks=False):
                            if depth < max_depth:
                                stack.append((de.path, depth + 1))
                        elif is_exe(de.name) and not is_junk_exe(de.name):
                            size = de.stat(follow_symlinks=False).st_size
                            if size > best_size:
                                best, best_size = de.path, size
                    except OSError:
                        continue
        except OSError:
            continue
    return best


def dir_size(root: str, max_depth: int = 6, max_entries: int = 50_000) -> int:
    """Approximate folder size (bounded walk so huge trees stay cheap)."""
    total, seen = 0, 0
    stack = [(root, 0)]
    while stack and seen < max_entries:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                for de in it:
                    seen += 1
                    try:
                        if de.is_dir(follow_symlinks=False):
                            if depth < max_depth:
                                stack.append((de.path, depth + 1))
                        else:
                            total += de.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def parse_yyyymmdd(value) -> datetime | None:
    if not value:
        return None
    s = re.sub(r"\D", "", str(value))[:8]
    try:
        return datetime.strptime(s, "%Y%m%d") if len(s) == 8 else None
    except ValueError:
        return None


def from_epoch(value) -> datetime | None:
    try:
        v = int(value)
        return datetime.fromtimestamp(v) if v > 0 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def file_mtime(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime)
    except OSError:
        return None


def env_path(var: str, *parts: str) -> str:
    base = os.environ.get(var)
    return os.path.join(base, *parts) if base else ""
