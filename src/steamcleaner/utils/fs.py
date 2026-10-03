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


def is_reparse_stat(path_stat: os.stat_result) -> bool:
    try:
        return bool(path_stat.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)  # Windows-only attr
    except AttributeError:
        return stat.S_ISLNK(path_stat.st_mode)


def is_reparse_point(path: Path) -> bool:
    try:
        return is_reparse_stat(path.lstat())
    except OSError:
        return path.is_symlink()


def is_gone(path: Path) -> bool:
    """Whether the file is verifiably absent: an error other than "not found" proves nothing."""
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def safe_rmtree(path: Path) -> bool:
    """Remove a directory tree, refusing to traverse reparse points."""
    if is_reparse_point(path):
        _logger.warning("Refusing to rmtree reparse point: %s", path)
        return False
    shutil.rmtree(path)
    return True


def walk_files(root: Path) -> Iterator[tuple[Path, int]]:
    """Yield (path, size) for each file under a directory. Reparse points and unreadable entries are skipped."""
    try:
        scanner = os.scandir(root)
    except OSError as scan_error:
        _logger.debug("Cannot scan directory %s: %s", root, scan_error)
        return
    with scanner:
        for entry in scanner:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not is_reparse_stat(entry.stat(follow_symlinks=False)):
                        yield from walk_files(Path(entry.path))
                    else:
                        _logger.debug("Skipping reparse point: %s", entry.path)
                elif entry.is_file(follow_symlinks=False) and not entry.is_symlink():
                    entry_stat = entry.stat(follow_symlinks=False)
                    if not is_reparse_stat(entry_stat):
                        yield Path(entry.path), entry_stat.st_size
            except OSError as file_error:
                _logger.debug("Error accessing %s: %s", entry.path, file_error)
                continue


def dir_size(path: Path) -> int:
    return sum(size for _, size in walk_files(path))


def measure_files(path: Path, platform: PlatformAdapter) -> dict[Path, FileAllocation]:
    """Return what every file at or under path occupies on disk. An uninspectable file is left out."""
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
    """Sum what deleting the measured files gives back. A hard-linked file counts when all its links are measured."""
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
    """Return what deleting the files at path gives back: allocation, not length, hard links as above."""
    return reclaimable_allocation(measure_files(path, platform).values())


def list_subdirs(path: Path) -> list[Path]:
    """List immediate subdirectories via os.scandir, skipping reparse points and what cannot be told to be one."""
    result: list[Path] = []
    try:
        scanner = os.scandir(path)
    except OSError as scan_error:
        _logger.debug("Cannot scan directory %s: %s", path, scan_error)
        return result
    with scanner:
        for entry in scanner:
            try:
                if entry.is_dir(follow_symlinks=False) and not is_reparse_stat(entry.stat(follow_symlinks=False)):
                    result.append(Path(entry.path))
            except OSError as dir_error:
                _logger.debug("Error accessing %s: %s", entry.path, dir_error)
                continue
    return result


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    value = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{size_bytes} B"  # pragma: no cover  # unreachable: TB iteration always returns
