"""StashScanner — parallel, streaming, cache-backed app discovery.

UI usage::

    scanner = StashScanner()
    items = scanner.get_cached()                 # instant, for startup
    scanner.start_scan(on_progress, on_done)     # background thread, done -> list[AppEntry]
    scanner.rescan(on_progress, on_diff)         # background thread, done -> ScanDiff

Callbacks are invoked from the worker thread; a Qt UI should forward them via signals.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable

from . import sources
from .cache import SQLiteCache
from .categorizer import categorize
from .models import AppEntry, ScanDiff, Source, norm_path

log = logging.getLogger("stash.scanner")

ProgressCb = Callable[[str, int], None]
DoneCb = Callable[[object], None]

_SOURCE_ENUM = {
    "Steam": Source.STEAM, "Epic": Source.EPIC, "GOG": Source.GOG, "Xbox": Source.XBOX,
    "Registry": Source.REGISTRY, "StartMenu": Source.STARTMENU, "Filesystem": Source.PORTABLE,
}


def _too_broad() -> set[str]:
    """Paths that must never 'claim' everything beneath them (badly-behaved installers)."""
    e = os.environ.get
    paths = {e("ProgramFiles"), e("ProgramFiles(x86)"), e("ProgramW6432"), e("LOCALAPPDATA"),
             e("APPDATA"), e("PROGRAMDATA"), e("SystemRoot"), os.path.expanduser("~"),
             "/usr/bin", "/usr/local/bin", "/usr", "/opt"}
    paths |= {f"{c}:\\" for c in "CDEFGH"}
    return {norm_path(p) for p in paths if p}


class ScanBusyError(RuntimeError):
    pass


class StashScanner:
    def __init__(self, cache_path: str | os.PathLike | None = None, max_workers: int = 4) -> None:
        self.cache = SQLiteCache(cache_path)
        self.max_workers = max_workers
        self.last_errors: dict[str, str] = {}
        self.last_duration: float = 0.0
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- public API -------------------------------------------------------
    def get_cached(self) -> list[AppEntry]:
        return self.cache.get_all()

    @property
    def is_scanning(self) -> bool:
        return self._lock.locked()

    def cancel(self) -> None:
        self._cancel.set()

    def start_scan(self, progress_cb: ProgressCb | None = None, done_cb: DoneCb | None = None,
                   blocking: bool = False, error_cb: Callable[[Exception], None] | None = None):
        """Full scan. ``done_cb(list[AppEntry])`` receives the complete, cached list."""
        return self._launch(False, progress_cb, done_cb, error_cb, blocking)

    def rescan(self, progress_cb: ProgressCb | None = None, done_cb: DoneCb | None = None,
               blocking: bool = False, error_cb: Callable[[Exception], None] | None = None):
        """Incremental scan. ``done_cb(ScanDiff)`` receives only added/updated/removed items."""
        return self._launch(True, progress_cb, done_cb, error_cb, blocking)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def close(self) -> None:
        self.cancel()
        self.wait(5)
        self.cache.close()

    # ---- internals --------------------------------------------------------
    def _launch(self, diff_mode, progress_cb, done_cb, error_cb, blocking):
        if not self._lock.acquire(blocking=False):
            raise ScanBusyError("A scan is already running")
        self._cancel.clear()

        def job():
            try:
                result = self._run(diff_mode, progress_cb)
                if done_cb and not self._cancel.is_set():
                    done_cb(result)
            except Exception as exc:  # never let the worker thread die silently
                log.exception("scan failed")
                if error_cb:
                    error_cb(exc)
                elif blocking:
                    raise
            finally:
                self.cache.close()  # drop idle connections between scans
                self._lock.release()

        if blocking:
            job()
            return None
        self._thread = threading.Thread(target=job, name="stash-scan", daemon=True)
        self._thread.start()
        return self._thread

    def _run(self, diff_mode: bool, progress_cb: ProgressCb | None):
        t0 = time.perf_counter()
        self.last_errors = {}
        old_fps = self.cache.fingerprints()  # id -> fp, tiny compared with full rows
        live_claims: set[str] = set()        # shared with the filesystem scanner (read-only there)
        broad = _too_broad()
        seen_ids: set[str] = set()
        claimed_dirs: set[str] = set()       # install dirs of accepted entries (dedupe)
        failed: set[Source] = set()
        diff = ScanDiff()
        total = 0

        def run_source(mod) -> list[AppEntry]:
            if self._cancel.is_set():
                return []
            entries = mod.scan()
            for e in entries:  # publish claims early so the filesystem walk can skip them
                for p in (norm_path(e.install_path), norm_path(e.exe_path)):
                    if p and p not in broad:
                        live_claims.add(p)
            return entries

        def under_claimed(path: str) -> bool:
            p = norm_path(path)
            for _ in range(8):
                if p in claimed_dirs:
                    return True
                parent = os.path.dirname(p)
                if parent == p:
                    return False
                p = parent
            return False

        def accept(name: str, entries: list[AppEntry], ancestor_check: bool) -> list[AppEntry]:
            kept = []
            for e in entries:
                if e.id in seen_ids:
                    continue
                d = norm_path(e.install_path)
                if d and (under_claimed(e.exe_path or d) if ancestor_check else d in claimed_dirs):
                    continue
                seen_ids.add(e.id)
                if d and d not in broad:
                    claimed_dirs.add(d)
                kept.append(e)
            return kept

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="stash-src") as pool:
            futures: list[tuple[object, Future]] = [(m, pool.submit(run_source, m)) for m in sources.PRIORITY_SOURCES]
            fs = sources.FALLBACK_SOURCE
            futures.append((fs, pool.submit(lambda: [] if self._cancel.is_set() else fs.scan(live_claims))))

            # Consume in priority order; each source's results are written and then dropped.
            for mod, fut in futures:
                name = mod.NAME
                try:
                    raw = fut.result()
                except Exception as exc:  # one broken source never kills the scan
                    log.warning("source %s failed: %s", name, exc, exc_info=True)
                    self.last_errors[name] = f"{type(exc).__name__}: {exc}"
                    failed.add(_SOURCE_ENUM[name])
                    raw = []
                if self._cancel.is_set():
                    continue
                kept = categorize(accept(name, raw, ancestor_check=mod in (sources.lnk, fs)))
                del raw
                changed = []
                for e in kept:
                    old = old_fps.get(e.id)
                    if old is None:
                        changed.append(e)
                        if diff_mode:
                            diff.added.append(e)
                    elif old != e.fingerprint():
                        changed.append(e)
                        if diff_mode:
                            diff.updated.append(e)
                self.cache.upsert(changed)
                total += len(kept)
                del kept, changed
                if progress_cb:
                    try:
                        progress_cb(name, total)
                    except Exception:
                        log.exception("progress callback failed")

        if self._cancel.is_set():
            return diff if diff_mode else []
        diff.removed = self.cache.delete_missing(seen_ids, keep_sources=[s.value for s in failed])
        self.cache.set_last_scan_time()
        self.last_duration = time.perf_counter() - t0
        log.info("scan finished: %d items in %.2fs", total, self.last_duration)
        return diff if diff_mode else self.cache.get_all()
