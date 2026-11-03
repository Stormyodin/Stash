"""Rule-based auto-categorisation of AppEntry objects."""
from __future__ import annotations

import os
import re
from typing import Iterable

from .models import AppEntry, Category, Source

_GAME_SOURCES = {Source.STEAM, Source.EPIC, Source.GOG, Source.XBOX}


def _rx(words: Iterable[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)


_DEV_EXES = {
    "python", "python3", "pythonw", "py", "git", "node", "npm", "code", "code-insiders", "cursor",
    "devenv", "idea64", "pycharm64", "webstorm64", "clion64", "rider64", "goland64", "datagrip64",
    "studio64", "java", "javac", "go", "cargo", "rustc", "gcc", "g++", "clang", "cmake", "make",
    "docker", "kubectl", "wsl", "pwsh", "powershell", "windowsterminal", "wt", "sublime_text",
    "notepad++", "postman", "insomnia", "dbeaver", "gh", "perl", "ruby", "php", "dotnet",
    "vim", "nvim", "gvim", "emacs", "ssh", "putty", "winscp", "filezilla", "heidisql", "ollama",
    "gdb", "lldb", "bash", "zsh", "conda", "pip", "pip3", "yarn", "pnpm", "deno", "bun",
}
_DEV_NAMES = _rx([
    "visual studio", "jetbrains", "intellij", "pycharm", "webstorm", "android studio", "git",
    "github desktop", "docker", "node.js", "python", "sublime text", "notepad++", "postman",
    "wireshark", "putty", "winscp", "filezilla", "cmake", "mingw", "msys2", "anaconda", "miniconda",
    "dbeaver", "sql server", "mysql", "postgresql", "unity hub", "unreal engine", "godot",
    "windows terminal", "powershell", "cursor", "neovim", "vim", "virtualbox", "vmware", "hyper-v",
])
_DEV_PUBLISHERS = _rx([
    "jetbrains", "github", "docker", "python software foundation", "git development community",
    "node.js foundation", "openjs foundation", "oracle", "postman", "sublime hq", "the qt company",
    "anaconda", "unity technologies", "epic games, inc. \\(unreal\\)",
])
_CREATIVE = _rx([
    "adobe", "photoshop", "illustrator", "premiere", "after effects", "lightroom", "indesign",
    "blender", "davinci", "resolve", "gimp", "inkscape", "krita", "affinity", "figma", "canva",
    "obs studio", "audacity", "fl studio", "ableton", "reaper", "cubase", "pro tools", "clip studio",
    "paint.net", "aseprite", "substance", "zbrush", "maya", "3ds max", "cinema 4d", "houdini",
    "sketchup", "autocad", "fusion 360", "capcut", "shotcut", "kdenlive", "handbrake", "darktable",
    "rawtherapee", "wallpaper engine",
])
_CREATIVE_EXES = {"blender", "gimp", "krita", "inkscape", "photoshop", "illustrator", "afterfx",
                  "resolve", "obs64", "obs", "audacity", "reaper", "fl64", "aseprite", "kdenlive"}
_MEDIA = _rx([
    "vlc", "spotify", "itunes", "apple music", "foobar2000", "winamp", "musicbee", "mpc-hc",
    "mpc-be", "potplayer", "kodi", "plex", "jellyfin", "netflix", "media player", "aimp",
    "mpv", "tidal", "deezer", "audible", "stremio", "k-lite", "codec",
])
_MEDIA_EXES = {"vlc", "spotify", "mpv", "kodi", "potplayer", "potplayermini64", "foobar2000",
               "itunes", "musicbee", "aimp", "totem", "rhythmbox", "ffmpeg", "ffplay"}
_GAME_PATH = re.compile(r"[\\/](games?|steamapps|steam|epic games|gog games|gog galaxy[\\/]games|"
                        r"xboxgames|riot games|ubisoft|origin games|ea games|battle\.net)[\\/]", re.I)
_GAME_PUBLISHERS = _rx([
    "valve", "riot games", "blizzard", "ubisoft", "electronic arts", "rockstar games", "bethesda",
    "cd projekt", "mojang", "square enix", "bandai namco", "capcom", "sega", "activision",
    "2k games", "paradox interactive", "devolver", "hoyoverse", "mihoyo", "krafton", "nexon",
])


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].lower() if path else ""


def categorize_one(e: AppEntry) -> Category:
    exe = _stem(e.exe_path)
    name, pub, path = e.name or "", e.publisher or "", e.install_path or e.exe_path or ""

    # 1. Specific tool names / executables win over generic source rules
    #    (e.g. Blender or Wallpaper Engine installed via Steam is Creative, not a game).
    if exe in _DEV_EXES:
        return Category.DEVTOOLS
    if exe in _CREATIVE_EXES or _CREATIVE.search(name):
        return Category.CREATIVE
    if exe in _MEDIA_EXES or _MEDIA.search(name):
        return Category.MEDIA
    if _DEV_NAMES.search(name) or _DEV_PUBLISHERS.search(pub):
        return Category.DEVTOOLS
    # 2. Game stores / launchers.
    if e.source in _GAME_SOURCES or "steam" in e.tags:
        return Category.GAMES
    # 3. Publisher & path heuristics.
    if _CREATIVE.search(pub):
        return Category.CREATIVE
    if _GAME_PUBLISHERS.search(pub) or _GAME_PATH.search(path):
        return Category.GAMES
    if re.search(r"\bmicrosoft\b", pub, re.I) and re.search(r"sdk|build tools|runtime|debug", name, re.I):
        return Category.DEVTOOLS
    # 4. Fallbacks by source.
    if e.source == Source.PORTABLE:
        return Category.PORTABLE
    if e.source in (Source.REGISTRY, Source.STARTMENU):
        return Category.APPS
    return Category.OTHER


def categorize(entries: list[AppEntry]) -> list[AppEntry]:
    """Assign ``category`` in place and return the same list."""
    for e in entries:
        e.category = categorize_one(e)
    return entries
