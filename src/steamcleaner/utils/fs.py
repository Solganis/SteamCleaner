from __future__ import annotations

import shutil
import stat
from pathlib import Path


def is_reparse_point(path: Path) -> bool:
    """Check if path is a symlink, junction, or other reparse point."""
    try:
        attrs = path.lstat().st_file_attributes  # type: ignore[attr-defined]
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except AttributeError, OSError:
        return path.is_symlink()


def safe_rmtree(path: Path) -> bool:
    """Remove a directory tree, refusing to traverse reparse points."""
    if is_reparse_point(path):
        return False
    shutil.rmtree(path)
    return True


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size_bytes_f = size_bytes / 1024
        if size_bytes_f < 1024 or unit == "TB":
            return f"{size_bytes_f:.1f} {unit}"
        size_bytes = int(size_bytes_f)
    return f"{size_bytes} B"  # pragma: no cover
