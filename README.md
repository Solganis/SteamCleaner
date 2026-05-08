# SteamCleaner

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

Files are sent to the trash by default, so you can always restore them if needed. Use **Dry Run** to preview what would be deleted without actually removing anything.

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
- Dry-run mode for previewing changes before committing

## License

GPL-3.0-or-later
