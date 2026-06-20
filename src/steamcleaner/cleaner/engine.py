import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.utils.fs import is_reparse_point

_logger = logging.getLogger(__name__)

CleanCallback = Callable[[JunkEntry, bool], None]


@dataclass(frozen=True, slots=True)
class CleanStats:
    """Outcome of a clean run: counts, freed bytes, and per-entry error messages."""

    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0


class CleanEngine:
    """Engine that deletes scanned junk, honoring dry-run, trash, and reparse-point safety."""

    def __init__(self, *, use_trash: bool = True, dry_run: bool = False) -> None:
        self._use_trash = use_trash
        self._dry_run = dry_run

    def clean(self, result: ScanResult, callback: CleanCallback | None = None) -> CleanStats:
        """Delete (or simulate deleting) every entry in result.

        Respects the engine's dry_run and use_trash settings, refuses to delete through
        reparse points, and invokes callback(entry, deleted) per entry when provided.

        Returns:
            CleanStats with deleted/skipped counts, freed bytes, and error messages.
        """
        deleted = 0
        skipped = 0
        errors: list[str] = []
        bytes_freed = 0

        _logger.info(
            "Starting clean: %d entries, dry_run=%s, use_trash=%s",
            len(result.entries),
            self._dry_run,
            self._use_trash,
        )

        for entry in result.entries:
            if not entry.path.exists():
                _logger.debug("Path no longer exists, skipping: %s", entry.path)
                skipped += 1
                continue

            if is_reparse_point(entry.path):
                _logger.warning("Refusing to delete reparse point: %s", entry.path)
                skipped += 1
                errors.append(f"Skipped symlink/junction: {entry.path}")
                if callback:
                    callback(entry, False)
                continue

            if self._dry_run:
                _logger.debug("Dry run: would delete %s (%d bytes)", entry.path, entry.size_bytes)
                deleted += 1
                bytes_freed += entry.size_bytes
                if callback:
                    callback(entry, True)
                continue

            try:
                self._delete(entry.path)
                _logger.info("Deleted: %s (%d bytes)", entry.path, entry.size_bytes)
                deleted += 1
                bytes_freed += entry.size_bytes
                if callback:
                    callback(entry, True)
            except (OSError, RuntimeError) as exc:
                _logger.error("Failed to delete %s: %s", entry.path, exc)
                skipped += 1
                errors.append(f"{entry.path}: {exc}")
                if callback:
                    callback(entry, False)

        _logger.info("Clean complete: %d deleted, %d skipped, %d bytes freed", deleted, skipped, bytes_freed)
        return CleanStats(deleted=deleted, skipped=skipped, errors=errors, bytes_freed=bytes_freed)

    def _delete(self, path: Path) -> None:
        if self._use_trash:
            send2trash(str(path))
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
