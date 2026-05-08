from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.utils.fs import is_reparse_point

CleanCallback = Callable[[JunkEntry, bool], None]


@dataclass(frozen=True, slots=True)
class CleanStats:
    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0


class CleanEngine:
    def __init__(self, *, use_trash: bool = True, dry_run: bool = False):
        self._use_trash = use_trash
        self._dry_run = dry_run

    def clean(self, result: ScanResult, callback: CleanCallback | None = None) -> CleanStats:
        deleted = 0
        skipped = 0
        errors: list[str] = []
        bytes_freed = 0

        for entry in result.entries:
            if not entry.path.exists():
                skipped += 1
                continue

            if is_reparse_point(entry.path):
                skipped += 1
                errors.append(f"Skipped symlink/junction: {entry.path}")
                if callback:
                    callback(entry, False)
                continue

            if self._dry_run:
                deleted += 1
                bytes_freed += entry.size_bytes
                if callback:
                    callback(entry, True)
                continue

            try:
                self._delete(entry.path)
                deleted += 1
                bytes_freed += entry.size_bytes
                if callback:
                    callback(entry, True)
            except Exception as exc:
                skipped += 1
                errors.append(f"{entry.path}: {exc}")
                if callback:
                    callback(entry, False)

        return CleanStats(deleted=deleted, skipped=skipped, errors=errors, bytes_freed=bytes_freed)

    def _delete(self, path: Path):
        if self._use_trash:
            send2trash(str(path))
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
