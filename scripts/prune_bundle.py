"""Remove from a built Windows bundle the parts of the Python runtime the app does not use.

`flet build` bundles a whole Python: every extension module, with Python 3.14 also its debug twin, the
Tcl/Tk libraries, and the full standard library. The app loads a fraction of it. What goes:

- A debug twin (`_ssl_d.pyd` beside `_ssl.pyd`). The bundle has no debug interpreter to load one.
- The Tcl/Tk libraries, when the bundle has no `_tkinter` to load them.
- SQLite, and the standard-library modules in `UNUSED_STDLIB`. None was loaded by the bundled app while
  it started, scanned and ran a dry-run clean. What still imports one of them among the modules that
  stay: `__main__` code (`asyncio.__main__`, the block at the end of `heapq`), a test (`certifi`), the
  `help()` builtin and the interactive-prompt hook of `site`, and `xmlrpc.server`, which nothing in the
  bundle imports.

Nothing is removed on a guess: a debug file without its release twin stays, and so do the Tcl/Tk libraries
of a bundle that has `_tkinter`. A layout the script does not know is refused.

Usage, after the bundle is built:
    uv run python scripts/prune_bundle.py build/windows
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Final

UNUSED_STDLIB: Final = (
    "_pyrepl",
    "bdb",
    "cProfile",
    "cmd",
    "code",
    "compileall",
    "curses",
    "dbm",
    "doctest",
    "imaplib",
    "mailbox",
    "modulefinder",
    "pdb",
    "pickletools",
    "poplib",
    "profile",
    "pstats",
    "pty",
    "pyclbr",
    "pydoc",
    "shelve",
    "sqlite3",
    "symtable",
    "timeit",
    "trace",
    "tty",
    "turtle",
    "unittest",
    "venv",
    "wave",
    "wsgiref",
    "zipapp",
)
SQLITE_BINARIES: Final = ("_sqlite3.pyd", "sqlite3.dll")
TCL_TK_GLOBS: Final = ("tcl*.dll", "libtommath.dll")
DEBUG_SUFFIXES: Final = ("_d.pyd", "_d.dll")


def find_debug_twins(binaries: Path) -> list[Path]:
    """Return the debug builds that sit beside their release build."""
    twins: list[Path] = []
    for binary in sorted(binaries.iterdir()):
        for suffix in DEBUG_SUFFIXES:
            release_name = binary.name.removesuffix(suffix) + suffix.removeprefix("_d")
            if binary.name.endswith(suffix) and (binaries / release_name).is_file():
                twins.append(binary)
    return twins


def find_unused(bundle: Path) -> list[Path]:
    """Return what can go from a bundle, or exit when it is not laid out as a Windows bundle."""
    stdlib = bundle / "Lib"
    binaries = bundle / "DLLs"
    if not (stdlib.is_dir() and binaries.is_dir()):
        sys.exit(f"ERROR: {bundle} has no Lib and DLLs directories, not a Windows bundle")
    unused = find_debug_twins(binaries)
    if not (binaries / "_tkinter.pyd").exists():
        unused.extend(found for pattern in TCL_TK_GLOBS for found in sorted(binaries.glob(pattern)))
    unused.extend(binaries / name for name in SQLITE_BINARIES)
    for name in UNUSED_STDLIB:
        unused.extend((stdlib / name, stdlib / f"{name}.pyc", stdlib / f"{name}.py"))
    return [path for path in unused if path.exists()]


def measure(path: Path) -> int:
    files = path.rglob("*") if path.is_dir() else (path,)
    return sum(file.stat().st_size for file in files if file.is_file())


def prune(bundle: Path) -> int:
    """Remove what the app does not use from the bundle and return the bytes that went."""
    removed_bytes = 0
    for path in find_unused(bundle):
        removed_bytes += measure(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        print(f"  removed {path.relative_to(bundle)}")
    return removed_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove the unused parts of the Python runtime from a bundle")
    parser.add_argument("bundle", type=Path, help="The built bundle, build/windows")
    args = parser.parse_args()
    removed_bytes = prune(args.bundle)
    print(f"Pruned {removed_bytes / (1024 * 1024):.1f} MB from {args.bundle}")


if __name__ == "__main__":
    main()
