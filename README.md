
# Stash

**Your PC library.** Every app, game and dev tool on your PC in one fast, macOS-style library for Windows.

[Download](https://github.com/Stormyodin/Stash/releases/latest) · [Build from source](#build-from-source) · [MIT License](LICENSE)

Stash looks through Steam, Epic, GOG, Xbox, the Windows registry, Start Menu shortcuts and portable folders. It caches what it finds in SQLite and shows it all in a dark, animated UI that stays light on RAM.

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

## Download and Run

Visit the [Stash Releases page](https://github.com/Stormyodin/Stash/releases/latest) to download the latest version.

There are two download options:

### Windows ZIP

The Windows ZIP contains the project files needed to build the Stash executable yourself.

1. Open the [latest release](https://github.com/Stormyodin/Stash/releases/latest).
2. Download the Windows ZIP asset from the Assets section.
3. Extract the ZIP file.
4. Open the extracted project folder.
5. Navigate to the `build` folder.
6. Run `build_windows.bat`.
7. Wait for the build process to finish.

The build script prepares the Python environment, installs the required dependencies and compiles Stash.

Once completed, the generated executable will be located at:

`build/dist/Stash.exe`

If Inno Setup 6 is installed, the build process can also generate a Windows installer in:

`build/Output/`

### Standalone Executable

Want to run Stash without building it yourself?

1. Open the [latest release](https://github.com/Stormyodin/Stash/releases/latest).
2. Find the standalone `Stash.exe` under Assets.
3. Download the executable.
4. Double-click it to launch Stash.

No Python installation or manual compilation is required for the standalone version.

> Windows 10/11 x64. The builds aren't code-signed yet, so SmartScreen may warn you. Click **More info → Run anyway** if you trust the downloaded file.

## Build from Source

### Requirements

- Windows 10 / 11 (64-bit)
- Python 3.11
- Inno Setup 6 (optional, required for generating the installer)

### Build Process

1. Download and extract the Windows ZIP from GitHub Releases.
2. Open the extracted project directory.
3. Navigate into the `build` folder.
4. Run `build_windows.bat`.
5. Allow the script to create its virtual environment and install dependencies.
6. Wait for PyInstaller to compile the application.

The standalone executable is generated first and placed in:

`build/dist/Stash.exe`

If Inno Setup 6 is installed, the installer is compiled afterward and placed in:

`build/Output/`

To run from source while developing:

```bash
pip install -r requirements.txt
python main.py              # Opens from cache; first run performs a full scan
python main.py --rescan     # Opens from cache, then performs an incremental rescan
python main.py --minimized  # Starts in the tray
```

> Don't use PySide6 **6.12.0** on Python 3.11. It breaks `None` refcounts and crashes the process. `requirements.txt` pins 6.9.3.

## Feature Details

| Area | What you get |
|---|---|
| Window | Frameless dark window with traffic-light controls, resizable edges and drag regions. Rounded corners and a dark frame via DWM on Windows 11. Position and size are restored on launch (QSettings). |
| Sidebar | Sections (All, Games, Apps, DevTools, Media & Creative, Portable, Other) with live counts and a sliding blue pill. Live fuzzy search, a rescan button with a radial progress ring, and "Last scanned X ago". |
| Grid | 160×180 cards with the icon, name, category badge and size. Hover scales the card to 1.03 with a blue glow (120 ms). Cards fade in 20 ms apart on startup. |
| List | 48 px rows with alternating backgrounds, an 80 ms hover transition, and size / badge / install date columns. |
| Details | 300 px panel that slides in from the right (200 ms ease-out-cubic). Launch, Open Folder, Copy Path and Uninstall. |
| Command palette | `Ctrl+K`: blurred backdrop, slide and fade, fuzzy top-12 results. `↑↓` to move, `↵` to launch, `⇧↵` to show the app in Stash, `Esc` to close. |
| Scanning | Full-window overlay on first run (ring, source chips, live count). Rescans merge in only what changed, with no full refresh flicker. Status bar shows scanning progress. |
| Tray (Windows) | Open, Command Palette, Rescan, Quit. Closing the window hides Stash to the tray and frees decoded icons. |
| Global hotkey | `Ctrl+K` works system-wide on Windows (`RegisterHotKey`). Change it with the `global_hotkey` QSettings key. |

**Shortcuts:** `Ctrl+K` palette · `Ctrl+F` search · `F5` / `Ctrl+R` rescan · `Ctrl+1` / `Ctrl+2` grid/list · `Esc` close.

## Performance Design

- **No widgets per item.** Grid and list share one `QListView` and one model, and custom delegates paint each item, so 2000 apps cost about as much as the entries themselves.
- **Icons load in the background.** A 2-thread `QThreadPool` uses a LIFO queue so visible icons come first. Icons are cached on disk at `~/.stash/icons/{id}.png` and kept in memory in a bounded LRU (384 pixmaps). Apps with no icon get a painted gradient squircle with their initials, so no bitmap is stored for them.
- **Animations are QPropertyAnimation only.** A single animation drives the whole staggered fade, and two drive hover in and out. Glows and shadows are painted directly instead of using `QGraphicsEffect` blur.
- **The palette blur is computed once.** It's a downscale and smooth upscale of a window snapshot, taken when the palette opens and freed when it closes.

## Layout

```text
main.py            entry point (single instance, dark palette, stylesheet)
core/              scanner core (sources, SQLite cache, categorizer)
ui/theme.py        colors, fonts, QSS
ui/window.py       MainWindow: sidebar, top bar, view, overlays, tray, scan flow
ui/delegates.py    AppView + grid/list delegates + animators
ui/model.py        AppModel (filter/sort/fuzzy, incremental ScanDiff merge)
ui/icons.py        async icon pipeline, Win32 extraction, placeholders
ui/details.py      details panel
ui/palette.py      Ctrl+K command palette
ui/overlay.py      first-run scan overlay
ui/widgets.py      traffic lights, section list, ring spinner, toggle, toast
ui/actions.py      launch / open folder / copy path / uninstall
ui/platform_win.py DWM styling, global hotkey, foreground helpers
```

## Platform Notes

The UI was developed and smoke-tested on Linux. Several features only work on Windows and have not been run there yet:

- Extracting icons from executables (ctypes `PrivateExtractIconsW`).
- DWM corner and dark-frame styling.
- Global hotkey.
- Tray behavior.
- Uninstall: Steam apps go to `steam://uninstall/<appid>`; other apps run the registry `UninstallString` via ShellExecute, which shows a UAC prompt if needed. If no uninstaller is registered, Stash opens Apps & Features instead.

## License

Stash is released under the MIT License. See [LICENSE](LICENSE) for details.
