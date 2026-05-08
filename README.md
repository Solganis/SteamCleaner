# SteamCleaner

[![CI](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/Solganis/SteamCleaner/actions/workflows/ci.yml)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-green.svg)](https://www.gnu.org/licenses/gpl-3.0)

Reclaim wasted disk space from Steam and other game clients.

SteamCleaner finds and safely removes junk files left behind by games — redistributable installers, shader caches, crash dumps, and old logs that pile up over time.

## Download

Requires Python 3.14+.

```bash
pip install steamcleaner
```

## Getting Started

Launch the app:

```bash
steamcleaner
```

1. Click **Scan** to find junk files
2. Review the results — each item shows its size, category, and path
3. Select what you want to remove (or use **Select All**)
4. Click **Clean Selected** to free up space

Files are sent to the trash by default, so you can always restore them if needed.

## What it finds

| Category | Examples |
|----------|---------|
| Redistributables | DirectX, VC++ installers bundled with games |
| Shader cache | Compiled shader caches per game |
| Crash dumps | `.dmp`, `.mdmp` files |
| Old logs | Log files over 1 MB |

## Safety

- Known game files are excluded automatically
- Symlinks and junction points are never followed
- Files go to trash by default, not permanent deletion

## License

GPL-3.0-or-later
