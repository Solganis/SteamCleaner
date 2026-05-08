# SteamCleaner

Cross-platform CLI/TUI tool for reclaiming disk space wasted by game clients.

Detects and safely removes redistributable installers, shader caches, crash dumps, and old logs left behind by Steam (more clients coming soon).

## Installation

Requires Python 3.14+.

```bash
pip install steamcleaner
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install steamcleaner
```

## Usage

### TUI (default)

```bash
steamcleaner
```

Interactive terminal UI with scan results table, row selection, and one-click cleanup.

### CLI

```bash
# Scan for junk
steamcleaner scan

# Delete with confirmation (sends to trash)
steamcleaner clean

# Preview what would be deleted
steamcleaner clean --dry-run

# Permanently delete instead of trashing
steamcleaner clean --no-trash
```

## What it finds

| Category | Examples |
|----------|---------|
| Redistributables | DirectX, VC++ installers bundled with games |
| Shader cache | Compiled shader caches per game |
| Crash dumps | `.dmp`, `.mdmp` files |
| Old logs | Log files over 1 MB |

## Safety

- Known-safe paths are excluded by default (e.g. `Steamworks Shared`, game files misplaced in `redist/` directories)
- Symlinks and junction points are never followed
- Files go to trash by default, not permanent deletion
- Dry-run mode available for previewing changes

## License

GPL-3.0-or-later
