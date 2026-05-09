# Steam Cleaner

[![Version](https://img.shields.io/github/v/release/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/releases)
[![CI](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/Solganis/SteamCleaner/graph/badge.svg?token=HFL1FA47T3)](https://codecov.io/github/Solganis/SteamCleaner)

[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/badge/type--checker-ty-D4AA00.svg)](https://github.com/astral-sh/ty)

[![i18n: EN | RU | ZH | ES | PT-BR](https://img.shields.io/badge/i18n-EN%20%7C%20RU%20%7C%20ZH%20%7C%20ES%20%7C%20PT--BR-blue.svg)](#languages)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![GitHub stars](https://img.shields.io/github/stars/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/Solganis/SteamCleaner)](https://github.com/Solganis/SteamCleaner/issues)

Cross-platform tool for reclaiming disk space from Steam, Epic Games, EA App, GOG Galaxy, and Ubisoft Connect.

Spiritual successor to [Codeusa/SteamCleaner](https://github.com/Codeusa/SteamCleaner) (archived, C#/.NET), rewritten from scratch in Python with significantly expanded detection capabilities, modern UI, and active development.

Games accumulate gigabytes of junk files over time: redistributable installers, shader caches, crash dumps, old logs, and unused cross-platform binaries. Steam Cleaner finds them and lets you safely remove what you don't need.

<!-- TODO: add screenshot when UI is finalized -->

## Features

- Desktop GUI built on [Flet](https://flet.dev/) with automatic OS theme detection (dark/light)
- Scans Steam, Epic Games, EA App (Origin), GOG Galaxy, and Ubisoft Connect
- Per-item selection with category badges, size breakdown, and sorting
- Search field for filtering results by path
- Context menu: open in file explorer, copy path to clipboard
- Determinate progress bar with per-file status during scan and deletion
- Keyboard shortcuts: Ctrl+A (select all), Delete (clean selected), Escape (cancel/deselect)
- Settings: trash vs permanent delete
- Safe by default: files go to system trash via [send2trash](https://github.com/arsenetar/Send2Trash), symlinks and junctions are never followed

## Supported clients

| Client | Game discovery | Launcher junk |
|--------|---------------|---------------|
| Steam | Registry, `libraryfolders.vdf`, Linux paths (native, Flatpak, Snap) | Shader cache, crash dumps |
| Epic Games | JSON manifests, Program Files, Wine/Proton prefixes | Logs, webcache |
| EA App (Origin) | Registry (`Origin Games`), Program Files, Wine/Proton prefixes | Logs, launcher cache |
| GOG Galaxy | Registry (`GOG.com\Games`), Program Files, Wine/Proton prefixes | Logs, crashdumps, webcache |
| Ubisoft Connect | Registry (`Ubisoft\Launcher\Installs`), default games dir, Wine/Proton prefixes | Cache, crashes, logs |

## What it finds

| Category | Examples | Typical savings |
|----------|----------|-----------------|
| Redistributable installers | DirectX, Visual C++, .NET, PhysX, OpenAL in `_CommonRedist`, `redist`, `__Installer` | 5-15 GB per library |
| Shader/web cache | Steam shader cache, Epic/GOG webcache, EA Desktop cache, Ubisoft Connect cache | Up to 500+ MB per client |
| Crash dumps | `.dmp`, `.mdmp` files in game directories and launcher crash folders | Varies |
| Old logs | Log files over 1 MB in game directories and launcher logs | Varies |
| Cross-platform binaries | Ren'Py `lib/darwin-*`, `lib/linux-*` on Windows (and vice versa) | Varies |
| Bundled installers | Setup/installer executables inside game folders | Varies |

## Safety

- Known game files are never touched (e.g. `Steamworks Shared`, `Heroes of the Storm`, `Penumbra Overture`, `Medieval II Total War`)
- Symlinks and junction points are never followed or deleted through
- Files go to system trash by default, not permanent deletion
- Each detected item shows its exact path, category, and size before removal

## Supported platforms

- Windows 10/11
- Linux (native, Flatpak, Snap)
- Wine/Proton: all non-Steam clients scan games installed through Wine, Proton (Steam Play), Bottles, and Lutris

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

GPL-3.0-or-later
