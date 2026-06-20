<h1 align="center">Steam Cleaner</h1>

<p align="center">
  <b>Reclaim disk space from Steam, Epic Games, EA App, GOG Galaxy, and Ubisoft Connect.</b><br>
  Spiritual successor to <a href="https://github.com/Codeusa/SteamCleaner">Codeusa/SteamCleaner</a> (archived, C#/.NET), rewritten from scratch in Python.
</p>

<p align="center">
  <a href="https://github.com/Solganis/SteamCleaner/releases"><img src="https://img.shields.io/github/v/release/Solganis/SteamCleaner" alt="Version"></a>
  <a href="https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml"><img src="https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/github/Solganis/SteamCleaner"><img src="https://codecov.io/github/Solganis/SteamCleaner/graph/badge.svg?token=HFL1FA47T3" alt="codecov"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.14-blue.svg" alt="Python 3.14"></a>
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"></a>
  <a href="https://github.com/astral-sh/ty"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json" alt="ty"></a>
  <br>
  <img src="https://img.shields.io/badge/i18n-EN%20%7C%20RU%20%7C%20ZH%20%7C%20ES%20%7C%20PT--BR-blue.svg" alt="i18n: EN | RU | ZH | ES | PT-BR">
</p>

<p align="center">
  <img src="assets/demo.gif" alt="SteamCleaner demo" width="720">
</p>

<p align="center">
  Games accumulate gigabytes of junk over time: redistributable installers, shader caches, crash dumps, old logs, unused cross-platform binaries.<br>
  Steam Cleaner finds them and lets you safely remove what you don't need.
</p>

---

## Quick start

Download the latest build from [Releases](https://github.com/Solganis/SteamCleaner/releases), run it, and press **Scan**.

To run from source:

```bash
uv sync
uv run steamcleaner
```

---

## Features

- **Cross-platform desktop app** (Windows, macOS, Linux) with automatic dark/light theme
- **Scans** Steam, Epic Games, EA App (Origin), GOG Galaxy, and Ubisoft Connect, including games installed through Wine, Proton, Bottles, Lutris, and other compatibility layers
- **Finds** redistributable installers, shader/web caches, crash dumps, old logs, bundled installers, and unused cross-platform binaries
- **Safe by default**: files go to system trash, symlinks and junctions are never followed
- **5 languages**: English, Russian, Chinese (Simplified), Spanish, Portuguese (Brazil)
- **Keyboard shortcuts** for scan, select, clean, and cancel

## What it finds

| Category | Examples |
|----------|----------|
| Redistributable installers | DirectX, Visual C++, .NET, PhysX, OpenAL in `_CommonRedist`, `redist`, `installer` |
| Shader/web cache | Steam shader cache, Epic/GOG webcache, EA Desktop cache, Ubisoft Connect cache |
| Crash dumps | `.dmp`, `.mdmp` files in game directories and launcher crash folders |
| Old logs | Log files over 1 MB in game directories and launcher logs |
| Cross-platform binaries | Ren'Py `lib/darwin-*`, `lib/linux-*` on Windows (and vice versa) |
| Bundled installers | Setup/installer executables inside game folders |

## Safety

- Known game files are never touched (e.g. `Steamworks Shared`, `Heroes of the Storm`, `Penumbra Overture`, `Medieval II Total War`)
- Symlinks and junction points are never followed or deleted through
- Files go to system trash by default, not permanent deletion
- Each detected item shows its exact path, category, and size before removal
