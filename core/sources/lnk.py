"""Start Menu shortcuts (.lnk) — parsed with a tiny pure-Python MS-SHLLINK reader (no COM)."""
from __future__ import annotations

import os
import struct
import sys

from ..models import AppEntry, Source
from ._common import env_path, file_mtime, is_exe, is_junk_exe

NAME = "StartMenu"
_HEADER_SIZE = 0x4C
_HAS_IDLIST, _HAS_LINKINFO = 0x01, 0x02


def _cstr(buf: bytes, off: int, wide: bool = False) -> str:
    if wide:
        end = off
        while end + 1 < len(buf) and buf[end:end + 2] != b"\0\0":
            end += 2
        return buf[off:end].decode("utf-16-le", "replace")
    end = buf.find(b"\0", off)
    return buf[off:end if end >= 0 else None].decode("mbcs" if sys.platform == "win32" else "latin-1", "replace")


def resolve_lnk(path: str) -> str:
    """Return the local target path of a .lnk file, or '' if it can't be resolved."""
    try:
        with open(path, "rb") as f:
            buf = f.read(64 * 1024)  # .lnk files are tiny; cap the read anyway
    except OSError:
        return ""
    if len(buf) < _HEADER_SIZE or struct.unpack_from("<I", buf, 0)[0] != _HEADER_SIZE:
        return ""
    flags = struct.unpack_from("<I", buf, 0x14)[0]
    off = _HEADER_SIZE
    if flags & _HAS_IDLIST:
        off += 2 + struct.unpack_from("<H", buf, off)[0]
    if not flags & _HAS_LINKINFO or off + 28 > len(buf):
        return ""
    li = off
    (li_size, li_hdr, li_flags, _vid, base_off, _net, suffix_off) = struct.unpack_from("<7I", buf, li)
    if not li_flags & 0x1:  # VolumeIDAndLocalBasePath
        return ""
    if li_hdr >= 0x24 and li + 36 <= len(buf):
        ubase, usuffix = struct.unpack_from("<2I", buf, li + 28)
        base, suffix = _cstr(buf, li + ubase, True), _cstr(buf, li + usuffix, True)
    else:
        base, suffix = _cstr(buf, li + base_off), _cstr(buf, li + suffix_off)
    return os.path.join(base, suffix) if suffix else base


def start_menu_dirs() -> list[str]:
    dirs = [env_path("APPDATA", "Microsoft", "Windows", "Start Menu", "Programs"),
            env_path("PROGRAMDATA", "Microsoft", "Windows", "Start Menu", "Programs")]
    return [d for d in dirs if d and os.path.isdir(d)]


def scan() -> list[AppEntry]:
    if sys.platform != "win32":
        return []
    out: list[AppEntry] = []
    seen: set[str] = set()
    for root in start_menu_dirs():
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".lnk"):
                    continue
                lnk = os.path.join(dirpath, fn)
                target = resolve_lnk(lnk)
                if not target or not is_exe(target) or is_junk_exe(os.path.basename(target)):
                    continue
                if not os.path.isfile(target):
                    continue
                e = AppEntry(
                    name=os.path.splitext(fn)[0], exe_path=target, install_path=os.path.dirname(target),
                    icon_path=target, size_bytes=os.path.getsize(target),
                    install_date=file_mtime(lnk), source=Source.STARTMENU, tags=["shortcut"],
                )
                if e.id not in seen:
                    seen.add(e.id)
                    out.append(e)
    return out
