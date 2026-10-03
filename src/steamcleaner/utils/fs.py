import logging
import os
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from steamcleaner.platform.base import FileAllocation, PlatformAdapter

_logger = logging.getLogger(__name__)


def is_reparse_point(path: Path) -> bool:
    """Check if path is a symlink, junction, or other reparse point."""
    try:
        attrs = path.lstat().st_file_attributes  # Windows-only attr
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):  # fmt: skip  # cosmic-ray (parso) lacks PEP 758
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


def measure_files(path: Path, platform: PlatformAdapter) -> dict[Path, FileAllocation]:
    """Return what every file at or under path occupies on disk.

    Reparse points are not followed and hold nothing. A file that cannot be inspected is left out.
    """
    if is_reparse_point(path):
        return {}
    file_paths = (file_path for file_path, _ in walk_files(path)) if path.is_dir() else (path,)
    allocations = {}
    for file_path in file_paths:
        try:
            allocations[file_path] = platform.file_allocation(file_path)
        except OSError as allocation_error:
            _logger.debug("Cannot measure %s: %s", file_path, allocation_error)
    return allocations


def reclaimable_allocation(allocations: Iterable[FileAllocation]) -> int:
    """Sum what deleting the measured files gives back.

    A file with several hard links counts only when every one of its links is among the measured files:
    deleting some of the names frees nothing.
    """
    total = 0
    linked_files: dict[tuple[int, int], tuple[int, int]] = {}
    for allocation in allocations:
        if allocation.link_count <= 1:
            total += allocation.allocated_bytes
            continue
        links_missing, _ = linked_files.get(allocation.file_id, (allocation.link_count, 0))
        linked_files[allocation.file_id] = (links_missing - 1, allocation.allocated_bytes)
    return total + sum(allocated for links_missing, allocated in linked_files.values() if links_missing == 0)


def disk_usage(path: Path, platform: PlatformAdapter) -> int:
    """Return the bytes the files at path occupy on disk, which is what deleting them gives back.

    Counts the allocation the filesystem reports, not file lengths, so compression, sparse holes and
    cluster rounding are reflected, with the hard-link rule of reclaimable_allocation. Directory metadata
    is not counted, and a file another process still holds open is released only when that process
    closes it.
    """
    return reclaimable_allocation(measure_files(path, platform).values())


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
