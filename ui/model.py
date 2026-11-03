"""Single list model shared by the grid and list views (delegates paint everything: zero widgets per item)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from core.models import AppEntry, Category, ScanDiff

from .fuzzy import match_entry

EntryRole = Qt.UserRole + 1
MatchRole = Qt.UserRole + 2

SECTIONS: list[tuple[str, str, frozenset | None]] = [
    ("all", "All", None),
    ("games", "Games", frozenset({Category.GAMES})),
    ("apps", "Apps", frozenset({Category.APPS})),
    ("dev", "DevTools", frozenset({Category.DEVTOOLS})),
    ("media", "Media & Creative", frozenset({Category.MEDIA, Category.CREATIVE})),
    ("portable", "Portable", frozenset({Category.PORTABLE})),
    ("other", "Other", frozenset({Category.OTHER})),
]
SECTION_CATS = {k: c for k, _, c in SECTIONS}
SORTS = ["Name", "Size", "Date Installed", "Last Used"]

_MIN = datetime.min


def _sort_key(name: str):
    if name == "Size":
        return (lambda e: -e.size_bytes), False
    if name == "Date Installed":
        return (lambda e: e.install_date or _MIN), True
    if name == "Last Used":
        return (lambda e: e.last_used or _MIN), True
    return (lambda e: e.name.casefold()), False


class AppModel(QAbstractListModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all: dict[str, AppEntry] = {}
        self._rows: list[AppEntry] = []
        self._matches: dict[str, tuple[int, ...]] = {}
        self.section = "all"
        self.query = ""
        self.sort = "Name"
        self.counts: dict[str, int] = {k: 0 for k, _, _ in SECTIONS}
        self.fade: dict[str, int] = {}  # id -> stagger rank for fade-in animations

    # ---- Qt model API -----------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        e = self._rows[index.row()]
        if role == EntryRole:
            return e
        if role == MatchRole:
            return self._matches.get(e.id, ())
        if role == Qt.DisplayRole:
            return e.name
        if role == Qt.ToolTipRole:
            return e.exe_path or e.install_path or e.launcher
        return None

    # ---- data access ------------------------------------------------------
    def entry(self, row: int) -> AppEntry | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def row_of(self, app_id: str) -> int:
        for i, e in enumerate(self._rows):
            if e.id == app_id:
                return i
        return -1

    def all_entries(self) -> list[AppEntry]:
        return list(self._all.values())

    def get(self, app_id: str) -> AppEntry | None:
        return self._all.get(app_id)

    def total(self) -> int:
        return len(self._all)

    # ---- mutations --------------------------------------------------------
    def set_entries(self, entries: list[AppEntry]) -> None:
        self._all = {e.id: e for e in entries}
        self._recount()
        self.beginResetModel()
        self._rows = self._compute()
        self.endResetModel()

    def set_view(self, section: str | None = None, query: str | None = None, sort: str | None = None) -> None:
        if section is not None:
            self.section = section
        if query is not None:
            self.query = query.strip().lower()
        if sort is not None:
            self.sort = sort
        self.beginResetModel()
        self._rows = self._compute()
        self.endResetModel()

    def apply_diff(self, diff: ScanDiff) -> list[str]:
        """Merge a ScanDiff with minimal row operations (no reset -> no flicker). Returns added ids."""
        for i in diff.removed:
            self._all.pop(i, None)
        for e in diff.updated:
            self._all[e.id] = e
        for e in diff.added:
            self._all[e.id] = e
        self._recount()
        self._sync(self._compute())
        return [e.id for e in diff.added]

    # ---- internals --------------------------------------------------------
    def _recount(self) -> None:
        counts = {k: 0 for k, _, _ in SECTIONS}
        counts["all"] = len(self._all)
        cat_to_key = {}
        for k, _, cats in SECTIONS:
            for c in cats or ():
                cat_to_key[c] = k
        for e in self._all.values():
            k = cat_to_key.get(e.category)
            if k:
                counts[k] += 1
        self.counts = counts

    def _compute(self) -> list[AppEntry]:
        cats = SECTION_CATS.get(self.section)
        items = self._all.values() if cats is None else [e for e in self._all.values() if e.category in cats]
        key, rev = _sort_key(self.sort)
        self._matches = {}
        if not self.query:
            return sorted(items, key=key, reverse=rev)
        q = self.query
        scored = []
        for e in items:
            m = match_entry(q, e.name, e.publisher, e.install_path or e.exe_path)
            if m is not None:
                scored.append((m[0], e))
                if m[1]:
                    self._matches[e.id] = m[1]
        scored.sort(key=lambda t: key(t[1]), reverse=rev)   # stable secondary order
        scored.sort(key=lambda t: t[0], reverse=True)       # primary: relevance
        return [e for _, e in scored]

    def _sync(self, target: list[AppEntry]) -> None:
        tgt_ids = [e.id for e in target]
        tgt_set = set(tgt_ids)
        # 1) removals, contiguous ranges from the bottom up
        r = len(self._rows) - 1
        while r >= 0:
            if self._rows[r].id in tgt_set:
                r -= 1
                continue
            end = r
            while r >= 0 and self._rows[r].id not in tgt_set:
                r -= 1
            self.beginRemoveRows(QModelIndex(), r + 1, end)
            del self._rows[r + 1:end + 1]
            self.endRemoveRows()
        # 2) reorder survivors if their relative order changed (e.g. size changed under size-sort)
        kept = {e.id for e in self._rows}
        order = [i for i in tgt_ids if i in kept]
        if [e.id for e in self._rows] != order:
            self.layoutAboutToBeChanged.emit()
            pos = {i: n for n, i in enumerate(order)}
            self._rows.sort(key=lambda e: pos[e.id])
            self.layoutChanged.emit()
        # 3) insertions, contiguous runs
        p = 0
        while p < len(target):
            if p < len(self._rows) and self._rows[p].id == tgt_ids[p]:
                p += 1
                continue
            q = p
            while q < len(target) and tgt_ids[q] not in kept:
                q += 1
            if q == p:  # should not happen; resync defensively
                self.beginResetModel()
                self._rows = list(target)
                self.endResetModel()
                return
            self.beginInsertRows(QModelIndex(), p, q - 1)
            self._rows[p:p] = target[p:q]
            self.endInsertRows()
            p = q
        # 4) swap in updated objects and repaint
        self._rows = list(target)
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))


# ---- formatting helpers ----------------------------------------------------
def fmt_size(n: int) -> str:
    if n <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def fmt_date(d: datetime | None) -> str:
    return d.strftime("%b %d, %Y") if d else "—"


def fmt_ago(d: datetime | None) -> str:
    if not d:
        return "never"
    s = (datetime.now() - d).total_seconds()
    if s < 60:
        return "just now"
    if s < 3600:
        v, u = int(s // 60), "minute"
    elif s < 86400:
        v, u = int(s // 3600), "hour"
    elif s < 86400 * 30:
        v, u = int(s // 86400), "day"
    elif s < 86400 * 365:
        v, u = int(s // (86400 * 30)), "month"
    else:
        v, u = int(s // (86400 * 365)), "year"
    return f"{v} {u}{'s' if v != 1 else ''} ago"
