
<div align="center">

# Stash

**A Unified Desktop Game Library**

Discover, organize, and launch games from multiple platforms through one lightweight desktop application.

[Download](https://github.com/Stormyodin/Stash/releases/latest) | [Build from Source](#building-from-source) | [License](LICENSE)

</div>

---

## Overview

Stash is a Windows desktop application that automatically detects installed games and organizes them into a single library. It supports multiple game launchers and installation sources while maintaining a responsive interface and low resource usage.

## Features

- **Automatic Game Detection:** Finds games from Steam, Epic Games, GOG, Xbox, the Windows Registry, Start Menu shortcuts, and portable folders.
- **Game Organization:** Automatically organizes detected games into categories.
- **Modern Interface:** Provides a clean dark interface with smooth animations and transitions.
- **Flexible Library Views:** Switch between grid and list layouts.
- **Command Palette:** Search for and launch games using `Ctrl + K`.
- **Fast Startup:** Uses a SQLite database to cache game information and reduce loading times.
- **Quick Actions:** Launch games, locate installations, and access common actions.
- **System Tray Integration:** Allows Stash to run in the background.
- **Startup Configuration:** Optionally launch Stash when Windows starts.

---

## Download

Visit the [latest release](https://github.com/Stormyodin/Stash/releases/latest) to access the available downloads.

| Package | Description |
|---|---|
| Windows ZIP | Contains the files required to build Stash locally. |
| Standalone Executable | Allows Stash to run directly without building from source. |

### System Requirements

- Windows 10 or Windows 11
- 64-bit operating system

---

## Building from Source

### Requirements

- Python 3.11
- Windows 10 or Windows 11 (64-bit)
- Inno Setup 6 (optional, for installer creation)

### Build Instructions

1. Download the Windows ZIP from the [latest release](https://github.com/Stormyodin/Stash/releases/latest).
2. Extract the downloaded archive.
3. Open the `build` directory.
4. Run `build_windows.bat`.
5. After the build completes, the executable will be available at:

   `build/dist/Stash.exe`

If Inno Setup 6 is installed, an installer will also be generated in:

`build/Output/`

### Running from Source

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Start the application:

```bash
python main.py
```

Additional launch options:

```bash
python main.py --rescan
python main.py --minimized
```

---

## Feature Details

| Component | Description |
|---|---|
| Game Scanner | Detects installed games from supported launchers and locations. |
| SQLite Cache | Stores game information to improve startup performance. |
| Command Palette | Provides keyboard-based game searching and launching. |
| Icon System | Downloads and stores game icons locally. |
| Library Views | Supports grid and list layouts. |
| System Tray | Provides background application access. |
| Quick Actions | Provides shortcuts to common game management actions. |

---

## Performance Design

Stash is designed to maintain responsiveness while managing large game libraries.

- SQLite caching reduces the need for repeated full scans.
- Background workers load game icons without blocking the interface.
- Downloaded icons are stored locally for reuse.
- A bounded in-memory cache limits unnecessary memory usage.
- Qt's `QListView` and custom delegates support efficient library rendering.
- The interface can load without waiting for every game icon.

---

## Project Structure

```text
Stash/
├── build/
├── core/
├── stash/
│   └── build/
├── ui/
├── main.py
├── requirements.txt
├── test_scanner.py
├── LICENSE
└── README.md
```

---

## Platform Support

Stash currently supports Windows 10 and Windows 11.

The application uses Windows-specific APIs for several features, including:

- Game icon extraction
- Window effects
- Global keyboard shortcuts
- System tray integration

---

## License

Stash is distributed under the MIT License.

Refer to the [LICENSE](LICENSE) file for the full license terms.

---

<div align="center">

**Stash**

A unified library for your games.

[GitHub Repository](https://github.com/Stormyodin/Stash)

</div>
