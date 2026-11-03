"""Smoke/integration test for the Stash scanner core (runs on Linux).

Builds small fake Steam / Epic / GOG / Xbox fixtures so the store parsers are exercised,
then runs a full scan, a no-op rescan, a rescan after changes, and a failing-source scan.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import tracemalloc
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

WORK = Path(tempfile.mkdtemp(prefix="stash_test_", dir=os.environ.get("TMPDIR") or str(Path.home())))


def build_fixtures() -> None:
    steam = WORK / "Steam"
    lib2 = WORK / "SteamLib2"
    for lib in (steam, lib2):
        (lib / "steamapps" / "common").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0"\n {\n  "path" "%s"\n }\n "1"\n {\n  "path" "%s"\n }\n}\n'
        % (str(steam).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")))

    def acf(lib: Path, appid: str, name: str, d: str) -> None:
        (lib / "steamapps" / "common" / d).mkdir()
        (lib / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n "appid" "{appid}"\n "name" "{name}"\n "installdir" "{d}"\n'
            f' "SizeOnDisk" "123456789"\n "buildid" "42"\n "LastUpdated" "1700000000"\n'
            f' "LastPlayed" "1710000000"\n}}\n')

    acf(steam, "620", "Portal 2", "Portal 2")
    acf(lib2, "1145360", "Hades", "Hades")
    acf(lib2, "365670", "Blender", "Blender")          # should be Creative, not Games
    acf(steam, "228980", "Steamworks Common Redistributables", "Steamworks Shared")  # skipped
    os.environ["STASH_STEAM_PATH"] = str(steam)

    epic = WORK / "EpicManifests"
    epic.mkdir()
    (epic / "abc.item").write_text(json.dumps({
        "DisplayName": "Fortnite", "InstallLocation": str(WORK / "Epic" / "Fortnite"),
        "LaunchExecutable": "FortniteGame/Binaries/Win64/FortniteLauncher.exe",
        "AppName": "Fortnite", "CatalogNamespace": "fn", "CatalogItemId": "4fe7",
        "AppVersionString": "++Fortnite+Release-30.00", "InstallSize": 987654321}))
    (epic / "bad.item").write_text("{not json")       # must be ignored gracefully
    os.environ["STASH_EPIC_MANIFESTS"] = str(epic)

    gogdb = WORK / "galaxy-2.0.db"
    con = sqlite3.connect(gogdb)
    con.executescript("""
        CREATE TABLE InstalledBaseProducts(productId INTEGER, installationPath TEXT, installationDate TEXT);
        CREATE TABLE LimitedDetails(productId INTEGER, title TEXT);
    """)
    con.execute("INSERT INTO InstalledBaseProducts VALUES(1207658924, ?, '2024-01-01')", (str(WORK / "GOG" / "Witcher 3"),))
    con.execute("INSERT INTO LimitedDetails VALUES(1207658924, 'The Witcher 3: Wild Hunt')")
    con.commit()
    con.close()
    os.environ["STASH_GOG_DB"] = str(gogdb)

    xbox = WORK / "XboxGames"
    content = xbox / "Halo Infinite" / "Content"
    content.mkdir(parents=True)
    (content / "HaloInfinite.exe").write_bytes(b"\0" * 2048)
    (content / "MicrosoftGame.config").write_text(
        '<?xml version="1.0"?><Game configVersion="1"><Identity Name="Microsoft.Halo" Version="1.2.3.0" '
        'Publisher="CN=Microsoft"/><ExecutableList><Executable Name="HaloInfinite.exe" Id="Game"/>'
        '</ExecutableList><ShellVisuals DefaultDisplayName="Halo Infinite" PublisherDisplayName="Xbox Game Studios" '
        'Square150x150Logo="Logo.png"/></Game>')
    os.environ["STASH_XBOX_PATH"] = str(xbox)


def check(cond: bool, msg: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    logging.basicConfig(level=logging.ERROR)  # expected source failure in step 6 logs a warning
    build_fixtures()
    from core import Category, ScanDiff, StashScanner, Source
    from core import sources
    from core.sources.lnk import resolve_lnk

    cache_path = WORK / "cache.db"
    scanner = StashScanner(cache_path=cache_path)

    print("1) get_cached() on first run")
    check(scanner.get_cached() == [], "cache is empty")
    check(scanner.cache.last_scan_time() is None, "no last_scan_time yet")

    print("2) start_scan()")
    progress: list[tuple[str, int]] = []
    result: dict = {}

    def on_progress(src: str, n: int) -> None:
        progress.append((src, n))
        print(f"     progress: {src:<11} total={n}")

    tracemalloc.start()
    t0 = time.perf_counter()
    th = scanner.start_scan(on_progress, lambda items: result.__setitem__("items", items))
    check(th is not None and scanner.is_scanning, "scan runs on a background thread")
    scanner.wait(120)
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    items = result.get("items")
    check(isinstance(items, list) and len(items) > 0, f"done_cb received {len(items or [])} items in {dt:.2f}s "
          f"(peak traced Python memory {peak / 1024 / 1024:.1f} MB)")
    check(len(progress) == 7, "progress emitted once per source (7 sources)")
    check(not scanner.last_errors, f"no source errors {scanner.last_errors}")

    by_cat = Counter(e.category.value for e in items)
    by_src = Counter(e.source.value for e in items)
    print("     by category:", dict(sorted(by_cat.items())))
    print("     by source:  ", dict(sorted(by_src.items())))

    names = {e.name: e for e in items}
    check("Portal 2" in names and names["Portal 2"].launcher == "steam://rungameid/620", "Steam game + launcher URI")
    check("Hades" in names, "second Steam library parsed from libraryfolders.vdf")
    check("Steamworks Common Redistributables" not in names, "Steam redistributables skipped")
    check(names.get("Blender") and names["Blender"].category == Category.CREATIVE, "Blender (Steam) -> Creative")
    check(names["Portal 2"].category == Category.GAMES and names["Portal 2"].last_used is not None, "Portal 2 -> Games, last_used set")
    check("Fortnite" in names and names["Fortnite"].source == Source.EPIC
          and names["Fortnite"].exe_path.endswith("FortniteLauncher.exe"), "Epic manifest parsed")
    check("The Witcher 3: Wild Hunt" in names and names["The Witcher 3: Wild Hunt"].source == Source.GOG, "GOG DB parsed")
    halo = names.get("Halo Infinite")
    check(halo is not None and halo.version == "1.2.3.0" and halo.publisher == "Xbox Game Studios", "Xbox MicrosoftGame.config parsed")
    dev = [e.name for e in items if e.category == Category.DEVTOOLS]
    check(any(n in dev for n in ("python3", "git", "bash", "perl")), f"dev tools detected ({len(dev)}: {dev[:6]}...)")
    check(len({e.id for e in items}) == len(items), "ids are unique")

    print("3) cache written")
    scanner2 = StashScanner(cache_path=cache_path)  # fresh instance -> reads from disk
    cached = scanner2.get_cached()
    check(len(cached) == len(items), f"cache holds {len(cached)} rows")
    check(scanner2.cache.last_scan_time() is not None, "last_scan_time recorded")
    mode = sqlite3.connect(cache_path).execute("PRAGMA journal_mode").fetchone()[0]
    check(mode.lower() == "wal", "SQLite journal_mode = WAL")
    c = next(e for e in cached if e.name == "Portal 2")
    check(c.size_bytes == 123456789 and c.install_date and c.tags == ["steam", "appid:620"], "row round-trips")
    scanner2.close()

    print("4) rescan() with no changes")
    out: dict = {}
    scanner.rescan(lambda s, n: None, lambda d: out.__setitem__("d", d), blocking=True)
    d = out["d"]
    check(isinstance(d, ScanDiff) and not d.changed, f"empty diff (+{len(d.added)} ~{len(d.updated)} -{len(d.removed)})")

    print("5) rescan() after install / uninstall / update")
    shutil.rmtree(WORK / "SteamLib2" / "steamapps" / "common" / "Hades")
    (WORK / "SteamLib2" / "steamapps" / "appmanifest_1145360.acf").unlink()
    acf_p2 = WORK / "Steam" / "steamapps" / "appmanifest_620.acf"
    acf_p2.write_text(acf_p2.read_text().replace('"buildid" "42"', '"buildid" "43"'))
    (WORK / "Steam" / "steamapps" / "common" / "Celeste").mkdir()
    (WORK / "Steam" / "steamapps" / "appmanifest_504230.acf").write_text(
        '"AppState"\n{\n "appid" "504230"\n "name" "Celeste"\n "installdir" "Celeste"\n}\n')
    scanner.rescan(None, lambda d: out.__setitem__("d", d), blocking=True)
    d = out["d"]
    check([e.name for e in d.added] == ["Celeste"], f"added: {[e.name for e in d.added]}")
    check([e.name for e in d.updated] == ["Portal 2"] and d.updated[0].version == "43", f"updated: {[e.name for e in d.updated]}")
    check(len(d.removed) == 1, f"removed: {len(d.removed)} (Hades)")
    names_now = {e.name for e in scanner.get_cached()}
    check("Celeste" in names_now and "Hades" not in names_now, "cache reflects diff")

    print("6) a crashing source doesn't kill the scan or wipe its cached rows")
    orig = sources.epic.scan
    sources.epic.scan = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        scanner.rescan(None, lambda d: out.__setitem__("d", d), blocking=True)
    finally:
        sources.epic.scan = orig
    check("Epic" in scanner.last_errors, f"error recorded: {scanner.last_errors}")
    check(not out["d"].removed and any(e.name == "Fortnite" for e in scanner.get_cached()), "Fortnite kept in cache")

    print("7) busy guard + lnk parser")
    from core import ScanBusyError
    scanner.start_scan()
    try:
        scanner.rescan()
        busy = False
    except ScanBusyError:
        busy = True
    scanner.wait(120)
    check(busy, "concurrent scan rejected with ScanBusyError")
    check(resolve_lnk(str(WORK / "missing.lnk")) == "", "resolve_lnk tolerates missing files")

    scanner.close()
    print(f"\nALL TESTS PASSED  ({len(items)} items, full scan {dt:.2f}s)")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
