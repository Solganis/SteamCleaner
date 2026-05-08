# SteamCleaner

[![GitHub stars](https://img.shields.io/github/stars/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/issues)
[![PyPI downloads](https://img.shields.io/pypi/dm/steamcleaner)](https://pypi.org/project/steamcleaner/)

[![CI](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/Solganis/SteamCleaner/graph/badge.svg?token=HFL1FA47T3)](https://codecov.io/github/Solganis/SteamCleaner)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checker-ty-D4AA00.svg)](https://github.com/astral-sh/ty)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-green.svg)](https://www.gnu.org/licenses/gpl-3.0)

Reclaim wasted disk space from Steam and other game clients.

SteamCleaner finds and safely removes junk files left behind by games. These files accumulate over time and can take up tens of gigabytes without you noticing.

<!-- TODO: add screenshot when UI is finalized -->

## Features

- Scans Steam libraries for junk files across all detected library folders
- Detects redistributables, shader caches, crash dumps, old logs, and cross-platform binaries
- Desktop GUI with per-item selection, category badges, and size breakdown
- CLI for scripting and automation (`steamcleaner scan`, `steamcleaner clean`)
- Safe by default: files go to system trash, symlinks are never followed
- Automatic OS theme detection (dark/light) with manual toggle
- Cross-platform: Windows and Linux

## What it finds

### Redistributable installers

Games bundle DirectX, Visual C++, .NET, PhysX, and OpenAL installers that run once during first launch and are never needed again. These sit in directories like `_CommonRedist`, `__Installer`, `redist`, `DirectX`, `miles`, and `support` inside each game folder. A typical Steam library with 50+ games can have 5-15 GB of these.

### Shader cache

Steam compiles and caches shaders per game in `steamapps/shadercache/`. These caches are rebuilt automatically when needed, but old entries for uninstalled games remain. Individual caches range from a few MB to 500+ MB for graphically intensive titles.

### Crash dumps

`.dmp` and `.mdmp` files generated when games or the Steam client crash. These are useful for developers but not for players. They accumulate in game directories and in `Steam/dumps/`.

### Old logs

Log files over 1 MB in game directories and `Steam/logs/`. Steam and many games write extensive logs that grow indefinitely. The Steam client log directory alone can reach several hundred MB on long-running installations.

### Cross-platform binaries

Games built with engines like Ren'Py ship binaries for all platforms (`lib/darwin-*`, `lib/linux-*` on Windows). These are completely unused on your OS.

## Safety

- Known game files are never touched (e.g. `Steamworks Shared`, game data misplaced in `redist/` directories)
- Symlinks and junction points are never followed or deleted through
- Files go to the system trash by default, not permanent deletion
- Each detected item shows its exact path and size before you decide to remove it

## Supported platforms

- Windows 10/11
- Linux (native, Flatpak, Snap)

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

GPL-3.0-or-later
