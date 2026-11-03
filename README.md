<p align="center">
  <img src="build/stash.png" width="96" alt="Stash icon">
</p>

<h1 align="center">Stash</h1>

<p align="center"><b>Your PC library.</b> Every app, game and dev tool on your PC in one fast, macOS-style library for Windows.</p>

<p align="center">
  <a href="https://github.com/your-username/stash/releases/latest">Download</a> ·
  <a href="build/README_BUILD.md">Build from source</a> ·
  <a href="LICENSE">MIT License</a>
</p>

Stash looks through Steam, Epic, GOG, Xbox, the Windows registry, Start Menu shortcuts and portable folders. It caches what it finds in SQLite and shows it all in a dark, animated UI that stays light on RAM.

## Screenshots

> _Screenshots coming soon._
>
> `docs/screenshot-grid.png` (grid view) · `docs/screenshot-palette.png` (Ctrl+K palette) · `docs/screenshot-details.png` (details panel)

## Features

- **One library for everything.** Pulls in Steam, Epic, GOG and Xbox / Microsoft Store titles, registry-installed apps, Start Menu shortcuts and portable apps.
- **Sorted for you.** Apps are grouped into Games, Apps, DevTools, Media & Creative, Portable and Other, with live counts.
- **macOS-inspired dark UI.** Frameless window with traffic-light controls, rounded Windows 11 corners and a sliding sidebar pill.
- **Smooth animations.** Staggered card fade-ins, hover glows, a slide-in details panel and a blurred command palette, all on a lightweight QPropertyAnimation pipeline.
- **Grid or list view.** Poster-style cards or compact rows. Switch with `Ctrl+1` / `Ctrl+2`.
- **Command palette (`Ctrl+K`).** Fuzzy-search and launch any app, from inside Stash or anywhere in Windows.
- **Instant startup.** Opens straight from a SQLite cache. Rescans only merge in what changed.
- **Light on RAM.** Virtualized views with no widget per item, a bounded icon cache and background icon loading.
- **Quick actions.** Launch, Open Folder, Copy Path and Uninstall from the details panel.
- **Runs in the tray.** Optional start on login. No admin rights needed.

## Installation

1. Download the latest **`Stash-Setup-x.y.z.exe`** from [GitHub Releases](https://github.com/your-username/stash/releases/latest).
2. Run it and follow the wizard. No admin rights are needed, and you can add a desktop shortcut or start on login.
3. Done. Stash opens and scans your PC on first run.

To skip installing, download the standalone **`Stash.exe`** from the same release and run it.

> Windows 10/11 x64. The builds aren't code-signed yet, so SmartScreen may warn you. Click **More info → Run anyway**.

## Build from source

See **[build/README_BUILD.md](build/README_BUILD.md)** for the full Windows build: Python 3.11 + Inno Setup 6, then `build\build_windows.bat`.

To run from source while developing:

```bash
pip install -r requirements.txt
python main.py            # opens instantly from cache; on first run it does a full scan
python main.py --rescan   # opens from cache, then does an incremental rescan
python main.py --minimized  # start in the tray (used by "Start on login")
```

> Don't use PySide6 **6.12.0** on Python 3.11. It breaks `None` refcounts and crashes the process. `requirements.txt` pins 6.9.3.

## Feature details

| Area | What you get |
|---|---|
| Window | Frameless dark window with traffic-light controls, resizable edges and drag regions. Rounded corners and a dark frame via DWM on Windows 11. Position and size are restored on launch (QSettings) |
| Sidebar | Sections (All, Games, Apps, DevTools, Media & Creative, Portable, Other) with live counts and a sliding blue pill. Live fuzzy search, a rescan button with a radial progress ring, and "Last scanned X ago" |
| Grid | 160×180 cards with the icon, name, category badge and size. Hover scales the card to 1.03 with a blue glow (120 ms). Cards fade in 20 ms apart on startup |
| List | 48 px rows with alternating backgrounds, an 80 ms hover transition, and size / badge / install date columns |
| Details | 300 px panel that slides in from the right (200 ms ease-out-cubic). Launch, Open Folder, Copy Path and Uninstall… |
| Command palette | `Ctrl+K`: blurred backdrop, slide and fade, fuzzy top-12 results. `↑↓` to move, `↵` to launch, `⇧↵` to show the app in Stash, `Esc` to close |
| Scanning | Full-window overlay on first run (ring, source chips, live count). Rescans merge in only what changed, with no full refresh flicker. Status bar shows "Scanning Steam… 47 found" |
| Tray (Windows) | Open, Command Palette, Rescan, Quit. Closing the window hides Stash to the tray and frees decoded icons |
| Global hotkey | `Ctrl+K` works system-wide on Windows (`RegisterHotKey`). Change it with the `global_hotkey` QSettings key |

Shortcuts: `Ctrl+K` palette · `Ctrl+F` search · `F5`/`Ctrl+R` rescan · `Ctrl+1`/`Ctrl+2` grid/list · `Esc` close.

## Performance design

- **No widgets per item.** Grid and list share one `QListView` and one model, and custom delegates paint each item, so 2000 apps cost about as much as the entries themselves.
- **Icons load in the background.** A 2-thread `QThreadPool` uses a LIFO queue so visible icons come first. Icons are cached on disk at `~/.stash/icons/{id}.png` and kept in memory in a bounded LRU (384 pixmaps). Apps with no icon get a painted gradient squircle with their initials, so no bitmap is stored for them.
- **Animations are QPropertyAnimation only.** A single animation drives the whole staggered fade, and two drive hover in and out. Glows and shadows are painted directly instead of using `QGraphicsEffect` blur.
- **The palette blur is computed once.** It's a downscale and smooth upscale of a window snapshot, taken when the palette opens and freed when it closes.

## Layout

```
main.py            entry point (single instance, dark palette, stylesheet)
core/              scanner core (sources, SQLite cache, categorizer)
ui/theme.py        colors, fonts, QSS
ui/window.py       MainWindow: sidebar, top bar, view, overlays, tray, scan flow
ui/delegates.py    AppView + grid/list delegates + animators
ui/model.py        AppModel (filter/sort/fuzzy, incremental ScanDiff merge)
ui/icons.py        async icon pipeline, Win32 extraction, placeholders, logo
ui/details.py      details panel
ui/palette.py      Ctrl+K command palette
ui/overlay.py      first-run scan overlay
ui/widgets.py      traffic lights, section list, ring spinner, toggle, toast
ui/actions.py      launch / open folder / copy path / uninstall
ui/platform_win.py DWM styling, global hotkey, foreground helpers
```

## Platform notes

The UI was developed and smoke-tested on Linux. Several features only work on Windows and have not been run there yet:

- extracting icons from executables (ctypes `PrivateExtractIconsW`)
- the DWM corner and dark-frame styling
- the global hotkey
- tray behavior
- uninstall: Steam apps go to `steam://uninstall/<appid>`; other apps run the registry `UninstallString` via ShellExecute, which shows a UAC prompt if needed; if no uninstaller is registered, Stash opens Apps & Features instead.
