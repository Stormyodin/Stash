"""Source scanners. Each module exposes NAME and scan() -> list[AppEntry].

Order matters: earlier sources win when two report the same program
(store/launcher metadata is richer than generic registry or filesystem data).
"""
from . import epic, filesystem, gog, lnk, registry, steam, xbox

PRIORITY_SOURCES = [steam, epic, gog, xbox, registry, lnk]
FALLBACK_SOURCE = filesystem  # runs last, skips paths claimed by the sources above

__all__ = ["PRIORITY_SOURCES", "FALLBACK_SOURCE", "steam", "epic", "gog", "xbox", "registry", "lnk", "filesystem"]
