"""Data models for Stash."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Source(str, Enum):
    REGISTRY = "Registry"
    STEAM = "Steam"
    EPIC = "Epic"
    GOG = "GOG"
    XBOX = "Xbox"
    STARTMENU = "StartMenu"
    PORTABLE = "Portable"


class Category(str, Enum):
    GAMES = "Games"
    APPS = "Apps"
    DEVTOOLS = "DevTools"
    MEDIA = "Media"
    CREATIVE = "Creative"
    PORTABLE = "Portable"
    OTHER = "Other"


def norm_path(path: str | None) -> str:
    """Normalize a path for comparison / hashing (case-insensitive on Windows)."""
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(path.strip().strip('"')))


def make_id(exe_path: str = "", install_path: str = "", launcher: str = "") -> str:
    """Stable id: hash of the exe path, falling back to launcher URI or install dir."""
    key = norm_path(exe_path) or launcher or norm_path(install_path)
    return hashlib.blake2b(key.encode("utf-8", "surrogatepass"), digest_size=10).hexdigest()


@dataclass(slots=True)
class AppEntry:
    name: str
    exe_path: str = ""
    install_path: str = ""
    icon_path: str = ""
    size_bytes: int = 0
    version: str = ""
    publisher: str = ""
    install_date: datetime | None = None
    last_used: datetime | None = None
    source: Source = Source.REGISTRY
    category: Category = Category.OTHER
    launcher: str = ""
    tags: list[str] = field(default_factory=list)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_id(self.exe_path, self.install_path, self.launcher)

    def fingerprint(self) -> str:
        """Hash of user-visible fields; used to detect changes on rescan."""
        raw = "\x1f".join((
            self.name, norm_path(self.exe_path), norm_path(self.install_path), self.icon_path,
            str(self.size_bytes), self.version, self.publisher, self.source.value,
            self.category.value, self.launcher, ",".join(self.tags),
            str(int(self.install_date.timestamp())) if self.install_date else "",
        ))
        return hashlib.blake2b(raw.encode("utf-8", "surrogatepass"), digest_size=8).hexdigest()


@dataclass(slots=True)
class ScanDiff:
    """Result of an incremental rescan."""
    added: list[AppEntry] = field(default_factory=list)
    updated: list[AppEntry] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # ids

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)
