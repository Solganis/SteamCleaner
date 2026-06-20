import logging
import os
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

_logger = logging.getLogger(__name__)


def is_reparse_point(path: Path) -> bool:
    """Check if path is a symlink, junction, or other reparse point."""
    try:
        attrs = path.lstat().st_file_attributes  # Windows-only attr
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    # parens required: ruff py314 removes them (PEP 758), but flet build bundles older Python
    except (AttributeError, OSError):  # fmt: skip
        return path.is_symlink()


def safe_rmtree(path: Path) -> bool:
    """Remove a directory tree, refusing to traverse reparse points."""
    if is_reparse_point(path):
        _logger.warning("Refusing to rmtree reparse point: %s", path)
        return False
    shutil.rmtree(path)
    return True


def walk_files(root: Path) -> Iterator[tuple[Path, int]]:
    """Walk directory tree via os.scandir, yielding (path, size) for each file.

    Uses DirEntry.stat() to avoid extra syscalls. Skips reparse points.
    """
    try:
        scanner = os.scandir(root)
    except OSError as scan_error:
        _logger.debug("Cannot scan directory %s: %s", root, scan_error)
        return
    with scanner:
        for entry in scanner:
            try:
                if entry.is_dir(follow_symlinks=False):
                    entry_path = Path(entry.path)
                    if not is_reparse_point(entry_path):
                        yield from walk_files(entry_path)
                    else:
                        _logger.debug("Skipping reparse point: %s", entry_path)
                elif entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                    yield Path(entry.path), entry.stat(follow_symlinks=False).st_size
            except OSError as file_error:
                _logger.debug("Error accessing %s: %s", entry.path, file_error)
                continue


def dir_size(path: Path) -> int:
    return sum(size for _, size in walk_files(path))


def list_subdirs(path: Path) -> list[Path]:
    """List immediate subdirectories via os.scandir, skipping reparse points."""
    result: list[Path] = []
    try:
        scanner = os.scandir(path)
    except OSError as scan_error:
        _logger.debug("Cannot scan directory %s: %s", path, scan_error)
        return result
    with scanner:
        for entry in scanner:
            try:
                if entry.is_dir(follow_symlinks=False):
                    entry_path = Path(entry.path)
                    if not is_reparse_point(entry_path):
                        result.append(entry_path)
            except OSError as dir_error:
                _logger.debug("Error accessing %s: %s", entry.path, dir_error)
                continue
    return result


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    value = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{size_bytes} B"  # pragma: no cover  # unreachable: TB iteration always returns
