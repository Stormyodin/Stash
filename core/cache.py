"""SQLite (WAL) cache for scan results."""
from __future__ import annotations

import os
import queue
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .models import AppEntry, Category, Source


def default_cache_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Stash"
    else:
        base = Path.home() / ".stash"
    return base / "cache.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exe_path TEXT, install_path TEXT, icon_path TEXT,
    size_bytes INTEGER DEFAULT 0,
    version TEXT, publisher TEXT,
    install_date REAL, last_used REAL,
    source TEXT, category TEXT, launcher TEXT, tags TEXT,
    fp TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_COLS = ("id", "name", "exe_path", "install_path", "icon_path", "size_bytes", "version",
         "publisher", "install_date", "last_used", "source", "category", "launcher", "tags", "fp")


def _ts(dt: datetime | None) -> float | None:
    return dt.timestamp() if dt else None


def _dt(v: float | None) -> datetime | None:
    try:
        return datetime.fromtimestamp(v) if v else None
    except (OverflowError, OSError, ValueError):
        return None


def _enum(cls, value, default):
    try:
        return cls(value)
    except ValueError:
        return default


class SQLiteCache:
    """Thread-safe cache backed by a tiny connection pool.

    Connections are borrowed per operation and returned immediately; at most
    ``max_idle`` idle connections are kept, and ``close()`` drops them all.
    """

    def __init__(self, path: str | os.PathLike | None = None, max_idle: int = 2) -> None:
        self.path = Path(path) if path else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._idle: queue.LifoQueue[sqlite3.Connection] = queue.LifoQueue(maxsize=max_idle)
        self._write_lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # ---- pool -----------------------------------------------------------
    def _new_conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10, check_same_thread=False, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("PRAGMA cache_size=-1024")  # ~1 MB page cache per connection
        return c

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        try:
            c = self._idle.get_nowait()
        except queue.Empty:
            c = self._new_conn()
        try:
            yield c
        finally:
            if c.in_transaction:
                c.rollback()
            try:
                self._idle.put_nowait(c)
            except queue.Full:
                c.close()

    def close(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return

    # ---- conversion -----------------------------------------------------
    @staticmethod
    def _to_row(e: AppEntry) -> tuple:
        return (e.id, e.name, e.exe_path, e.install_path, e.icon_path, int(e.size_bytes or 0),
                e.version, e.publisher, _ts(e.install_date), _ts(e.last_used), e.source.value,
                e.category.value, e.launcher, "\x1f".join(e.tags), e.fingerprint())

    @staticmethod
    def _from_row(r: tuple) -> AppEntry:
        return AppEntry(
            id=r[0], name=r[1], exe_path=r[2] or "", install_path=r[3] or "", icon_path=r[4] or "",
            size_bytes=r[5] or 0, version=r[6] or "", publisher=r[7] or "",
            install_date=_dt(r[8]), last_used=_dt(r[9]),
            source=_enum(Source, r[10], Source.REGISTRY),
            category=_enum(Category, r[11], Category.OTHER),
            launcher=r[12] or "", tags=[t for t in (r[13] or "").split("\x1f") if t],
        )

    # ---- public API -----------------------------------------------------
    def iter_all(self, batch: int = 256) -> Iterator[AppEntry]:
        """Stream entries without materialising the whole table."""
        with self._conn() as c:
            cur = c.execute(f"SELECT {','.join(_COLS[:-1])} FROM apps ORDER BY name COLLATE NOCASE")
            while rows := cur.fetchmany(batch):
                for r in rows:
                    yield self._from_row(r)

    def get_all(self) -> list[AppEntry]:
        return list(self.iter_all())

    def get_many(self, ids: Iterable[str]) -> list[AppEntry]:
        ids = list(ids)
        out: list[AppEntry] = []
        with self._conn() as c:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = f"SELECT {','.join(_COLS[:-1])} FROM apps WHERE id IN ({','.join('?' * len(chunk))})"
                out.extend(self._from_row(r) for r in c.execute(q, chunk))
        return out

    def fingerprints(self) -> dict[str, str]:
        """id -> fingerprint map (small; used for incremental diffing)."""
        with self._conn() as c:
            return dict(c.execute("SELECT id, fp FROM apps"))

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM apps").fetchone()[0]

    def upsert(self, entries: Iterable[AppEntry]) -> int:
        rows = [self._to_row(e) for e in entries]
        if not rows:
            return 0
        sql = (
            f"INSERT INTO apps ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))}) "
            "ON CONFLICT(id) DO UPDATE SET "
            + ",".join(f"{k}=excluded.{k}" for k in _COLS[1:] if k != "last_used")
            + ", last_used=COALESCE(excluded.last_used, apps.last_used)"
        )
        with self._write_lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.executemany(sql, rows)
            c.execute("COMMIT")
        return len(rows)

    def delete_missing(self, current_ids: Iterable[str], keep_sources: Iterable[str] = ()) -> list[str]:
        """Delete rows whose id is not in ``current_ids``; returns deleted ids.

        Rows whose ``source`` is in ``keep_sources`` are preserved (e.g. a source that
        failed this scan shouldn't wipe its previously cached entries).
        """
        keep = set(current_ids)
        keep_src = set(keep_sources)
        with self._write_lock, self._conn() as c:
            gone = [i for (i, s) in c.execute("SELECT id, source FROM apps")
                    if i not in keep and s not in keep_src]
            if gone:
                c.execute("BEGIN IMMEDIATE")
                c.executemany("DELETE FROM apps WHERE id=?", ((i,) for i in gone))
                c.execute("COMMIT")
        return gone

    def last_scan_time(self) -> datetime | None:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='last_scan'").fetchone()
        return _dt(float(row[0])) if row else None

    def set_last_scan_time(self, when: datetime | None = None) -> None:
        ts = when.timestamp() if when else time.time()
        with self._write_lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('last_scan', ?)", (str(ts),))
