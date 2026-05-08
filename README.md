# SteamCleaner

[![GitHub stars](https://img.shields.io/github/stars/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/issues)

[![CI](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/Solganis/SteamCleaner/graph/badge.svg?token=HFL1FA47T3)](https://codecov.io/github/Solganis/SteamCleaner)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checker-ty-D4AA00.svg)](https://github.com/astral-sh/ty)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-green.svg)](https://www.gnu.org/licenses/gpl-3.0)

Cross-platform tool for reclaiming disk space from game clients. Spiritual successor to [Codeusa/SteamCleaner](https://github.com/Codeusa/SteamCleaner) (archived, C#/.NET), rewritten from scratch in Python.

Games accumulate gigabytes of junk files over time: redistributable installers, shader caches, crash dumps, old logs, and unused cross-platform binaries. SteamCleaner finds them and lets you safely remove what you don't need.

<!-- TODO: add screenshot when UI is finalized -->

## Features

- Desktop GUI built on [Flet](https://flet.dev/) with automatic OS theme detection (dark/light)
- Scans all detected Steam library folders, including external drives
- Per-item selection with category badges, size breakdown, and sorting
- Search field for filtering results by path
- Context menu: open in file explorer, copy path to clipboard
- Determinate progress bar with per-file status during scan and deletion
- Safe by default: files go to system trash via [send2trash](https://github.com/arsenetar/Send2Trash), symlinks and junctions are never followed

## What it finds

| Category | Examples | Typical savings |
|----------|----------|-----------------|
| Redistributable installers | DirectX, Visual C++, .NET, PhysX, OpenAL in `_CommonRedist`, `redist`, `DirectX` | 5-15 GB per library |
| Shader cache | `steamapps/shadercache/` entries for uninstalled games | Up to 500+ MB per game |
| Crash dumps | `.dmp`, `.mdmp` files in game directories and `Steam/dumps/` | Varies |
| Old logs | Log files over 1 MB in game directories | Varies |
| Cross-platform binaries | Ren'Py `lib/darwin-*`, `lib/linux-*` on Windows (and vice versa) | Varies |
| Bundled installers | Setup/installer executables inside game folders | Varies |

## Safety

- Known game files are never touched (e.g. `Steamworks Shared`, game data misplaced in `redist/` directories)
- Symlinks and junction points are detected via `is_reparse_point()` and never followed or deleted through
- Files go to system trash by default, not permanent deletion
- Each detected item shows its exact path, category, and size before removal
- Built-in exclusion registry with support for user-defined exclusions via config

## Supported platforms

- Windows 10/11
- Linux (native, Flatpak, Snap)

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

GPL-3.0-or-later
