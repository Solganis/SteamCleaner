# SteamCleaner

Cross-platform CLI/TUI tool for reclaiming disk space from game clients (Steam, Epic, EA App, GOG, Ubisoft Connect, Xbox, Battle.net).
Spiritual successor to [Codeusa/SteamCleaner](https://github.com/Codeusa/SteamCleaner) (archived, C#/.NET), rewritten from scratch on Python.

## Stack

- Python 3.14+, uv, pyproject.toml
- Ruff (lint + format)
- textual (TUI), click (CLI)
- pytest, send2trash
- PyInstaller / Nuitka (release binary)
- License: GPL-3.0-or-later

## Project Structure

```
src/steamcleaner/
├── app.py                    # entry point, wiring
├── __main__.py               # python -m steamcleaner
├── models/
│   ├── junk.py               # JunkEntry (frozen dataclass), JunkCategory (StrEnum)
│   └── scan_result.py        # ScanResult (aggregate, filtering, grouping)
├── platform/
│   ├── base.py               # PlatformAdapter (ABC): registry, appdata, home
│   ├── windows.py            # WindowsAdapter (winreg, AppData)
│   ├── linux.py              # LinuxAdapter (XDG, ~/.local/share)
│   └── macos.py              # MacOSAdapter (~/Library)
├── clients/
│   ├── base.py               # GameClient (ABC): name, is_installed, find_paths, scan_junk, scan_safe
│   ├── registry.py           # ClientRegistry: @register decorator, auto-discovery
│   ├── steam.py              # libraryfolders.vdf + config.vdf fallback
│   ├── epic.py
│   ├── ea_app.py             # бывший Origin
│   ├── gog.py
│   ├── ubisoft.py            # бывший Uplay
│   ├── xbox.py
│   └── battlenet.py
├── scanner/
│   ├── engine.py             # ScanEngine (orchestrator, progress callback)
│   ├── patterns.py           # JunkPattern (dataclass), COMMON_PATTERNS
│   └── exclusions.py         # ExclusionRegistry (builtin + user TOML)
├── cleaner/
│   └── engine.py             # CleanEngine (dry-run, send2trash, shutil.rmtree)
├── ui/
│   ├── cli.py                # click CLI
│   └── tui/                  # textual app, screens, widgets
└── utils/
    ├── fs.py                 # is_reparse_point, safe_resolve, safe_rmtree, size formatting
    ├── vdf.py                # Valve VDF parser
    └── config.py             # TOML config loader (~/.config/steamcleaner/)
```

## Architecture Conventions

### Adding a New Game Client

1. Create `src/steamcleaner/clients/<name>.py`
2. Subclass `GameClient`, implement all abstract methods
3. Decorate with `@ClientRegistry.register`
4. No wiring needed: discovery is automatic

### Key Abstractions

- `GameClient` owns the full pipeline: detect install → find libraries → scan junk. Each client yields `JunkEntry` bound to itself (unlike original where paths were pooled).
- `PlatformAdapter` injected via DI. Clients never import `winreg` or hardcode OS paths directly.
- `ExclusionRegistry` injected into `GameClient`. Filtering happens in `scan_safe()`, not in individual `scan_junk()`.
- `ScanEngine` orchestrates clients. `CleanEngine` handles deletion. Between them: `ScanResult` as the contract.
- Models (`JunkEntry`, `ScanResult`) are pure data, no IO, no side effects.

### Exclusions (from original repo bugs)

These paths must NEVER be deleted (games store real data there):

- `Steamworks Shared` (shared redistributable pool, issue #74)
- `Heroes of the Storm` / `StarCraft` (game files in `support/`)
- `Penumbra Overture/redist` (actual game data)
- `Medieval II Total War/miles` (Miles Sound System, part of engine)

### Junk Detection Patterns

Primary regex from original: `(directx|redist|_commonredist|miles|support|installer)` on directory names, then filter by extensions `.cab`, `.exe`, `.msi`, `.so`.
Additional: Ren'Py cross-platform binaries (`lib/darwin-*`, `lib/linux-*`), shader cache, crash dumps (`.dmp`, `.mdmp`), old logs (>1MB).

### Symlink Safety

Steam supports junction points for libraries on different drives. Always check `is_reparse_point()` before deletion. `safe_rmtree()` refuses to delete through symlinks/junctions.

### Steam Path Discovery

- Windows registry: `HKLM\SOFTWARE\Wow6432Node\Valve\Steam\InstallPath` (64-bit) / `HKLM\SOFTWARE\Valve\Steam\InstallPath` (32-bit)
- Linux: `~/.steam/steam`, `~/.local/share/Steam`, Flatpak/Snap paths
- macOS: `~/Library/Application Support/Steam`
- Library folders: parse `libraryfolders.vdf` (modern), fallback `config.vdf` `BaseInstallFolder_N` (legacy)

## Git Conventions

- Commit messages follow [Google's Python style guide](https://google.github.io/styleguide/pyguide.html) conventions
- Format: `type(scope): short description` (lowercase, no period)
- Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`
- Scope: module or area affected, e.g. `scanner`, `tui`, `clients`
- Body (optional): explain **why**, not what
- No AI attribution in commit messages

## Code Style

- `src/` layout with `pyproject.toml`
- Type hints on everything, never `-> None`
- `frozen=True, slots=True` on all dataclasses
- `StrEnum` for categories, `match/case` where appropriate
- No bare `except`. Catch specific exceptions.
- Ruff line-length 120
- Docstrings: Google style, concise

## Testing

- Fixture directories in `tests/fixtures/` with fake game trees
- `PlatformAdapter` mocked via DI, tests OS-independent
- Exclusion coverage: every builtin exclusion has a dedicated test
- Symlink/junction tests with `tmp_path`
- Unicode path tests (Cyrillic, CJK)
- `CleanEngine`: always test `dry_run=True` first

## Config

User config at `~/.config/steamcleaner/config.toml`:
- `scan.custom_paths`: additional directories to scan
- `scan.exclusions`: user-defined exclusions (pattern + reason)
- `clean.dry_run`, `clean.use_trash`, `clean.min_size_mb`
- `ui.mode`: "cli" or "tui"
