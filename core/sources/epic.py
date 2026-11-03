"""Epic Games Launcher manifests (*.item JSON)."""
from __future__ import annotations

import json
import os

from ..models import AppEntry, Source
from ._common import IS_WIN, file_mtime

NAME = "Epic"


def manifest_dir() -> str:
    override = os.environ.get("STASH_EPIC_MANIFESTS")
    if override:
        return override
    if IS_WIN:
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(base, "Epic", "EpicGamesLauncher", "Data", "Manifests")
    # Linux stub (Heroic/Legendary store data elsewhere; not supported yet).
    return os.path.expanduser("~/.config/Epic/EpicGamesLauncher/Data/Manifests")


def scan() -> list[AppEntry]:
    d = manifest_dir()
    if not os.path.isdir(d):
        return []
    out: list[AppEntry] = []
    with os.scandir(d) as it:
        files = [de.path for de in it if de.name.endswith(".item")]
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("bIsIncompleteInstall"):
            continue
        name, loc = m.get("DisplayName"), m.get("InstallLocation")
        if not name or not loc:
            continue
        rel = m.get("LaunchExecutable") or ""
        exe = os.path.normpath(os.path.join(loc, rel)) if rel else ""
        ns, item, app = m.get("CatalogNamespace", ""), m.get("CatalogItemId", ""), m.get("AppName", "")
        launcher = (f"com.epicgames.launcher://apps/{ns}%3A{item}%3A{app}?action=launch&silent=true"
                    if app else "")
        out.append(AppEntry(
            name=name, exe_path=exe, install_path=os.path.normpath(loc), icon_path=exe,
            size_bytes=int(m.get("InstallSize", 0) or 0), version=str(m.get("AppVersionString", "")),
            install_date=file_mtime(path), source=Source.EPIC, launcher=launcher,
            tags=["epic"] + [c for c in (m.get("AppCategories") or []) if isinstance(c, str)][:4],
        ))
    return out
