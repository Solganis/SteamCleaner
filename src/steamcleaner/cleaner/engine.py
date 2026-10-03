import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from send2trash import send2trash

from steamcleaner.models.junk import GUARDED_CATEGORIES, JunkEntry
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import is_reparse_point, measure_files, reclaimable_allocation

if TYPE_CHECKING:
    from pathlib import Path

    from steamcleaner.models.scan_result import ScanResult
    from steamcleaner.platform.base import PlatformAdapter

_logger = logging.getLogger(__name__)

CleanCallback = Callable[[JunkEntry, bool], None]


def _stands_unchecked(entry: JunkEntry) -> bool:
    """Whether an entry may be deleted on the word of the scan alone: all but the guarded categories."""
    return entry.category not in GUARDED_CATEGORIES


def _is_gone(path: Path) -> bool:
    """Whether the file is verifiably absent: an error other than "not found" proves nothing."""
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanStats:
    """Outcome of a clean run: counts, per-entry error messages, and where the bytes went.

    bytes_freed is the on-disk allocation of what was deleted for good. bytes_trashed is the allocation of
    what was moved to the trash, which still occupies the disk until the trash is emptied. Both are what
    the filesystem reported for the files: a file another process still holds open is released only when
    that process closes it, and directory metadata is not counted. In a dry run the same fields report
    what the run would have removed.
    """

    deleted: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    bytes_trashed: int = 0


class CleanEngine:
    """Engine that deletes scanned junk, honoring dry-run, trash, exclusion, and reparse-point safety."""

    def __init__(
        self,
        *,
        use_trash: bool = True,
        dry_run: bool = False,
        exclusions: ExclusionRegistry | None = None,
        platform: PlatformAdapter | None = None,
        still_offered: Callable[[JunkEntry], bool] | None = None,
    ) -> None:
        self._use_trash = use_trash
        self._dry_run = dry_run
        self._still_offered = _stands_unchecked if still_offered is None else still_offered
        # Enforce the never-delete list at delete time, not only during scan_safe(). Default to the
        # builtins so the guarantee holds even when a caller wires no registry; this is the last-line
        # guard against a protected path reaching deletion via custom_paths, a bug, or a future path.
        self._exclusions = exclusions or ExclusionRegistry()
        self._platform = platform

    def clean(self, result: ScanResult, callback: CleanCallback | None = None) -> CleanStats:
        """Delete (or simulate deleting) every entry in result.

        Respects the engine's dry_run and use_trash settings, refuses to delete a path that is on the
        exclusion list or is itself a reparse point, and invokes callback(entry, deleted) per entry
        when provided. A result can be minutes old by the time it is cleaned, so the engine asks
        still_offered about each entry it is about to remove and leaves alone one that is not confirmed.
        Without still_offered it confirms every entry except those of the guarded categories.

        Entries are handled parents first. One nested under an entry that was just removed, or listed a
        second time, went with it: it counts as deleted, adds no bytes of its own and is not asked about.

        With a platform the engine measures each entry right before removing it, and when a removal fails
        part-way it counts the files that are verifiably gone. Without one it trusts the size the scan
        recorded and counts nothing for an entry that failed.

        Returns:
            CleanStats with deleted/skipped counts, freed or trashed bytes, and error messages.
        """
        deleted = 0
        skipped = 0
        errors: list[str] = []
        bytes_removed = 0
        removed_paths: set[Path] = set()

        _logger.info(
            "Starting clean: %d entries, dry_run=%s, use_trash=%s",
            len(result.entries),
            self._dry_run,
            self._use_trash,
        )

        for entry in sorted(result.entries, key=lambda entry: len(entry.path.parts)):
            if entry.path in removed_paths or not removed_paths.isdisjoint(entry.path.parents):
                _logger.debug("Already removed with an earlier entry: %s", entry.path)
                deleted += 1
                if callback:
                    callback(entry, True)
                continue

            if not entry.path.exists():
                _logger.debug("Path no longer exists, skipping: %s", entry.path)
                skipped += 1
                continue

            if self._exclusions.is_excluded(entry.path):
                _logger.warning("Refusing to delete excluded path: %s", entry.path)
                skipped += 1
                errors.append(f"Skipped protected path: {entry.path}")
                if callback:
                    callback(entry, False)
                continue

            if is_reparse_point(entry.path):
                _logger.warning("Refusing to delete reparse point: %s", entry.path)
                skipped += 1
                errors.append(f"Skipped symlink/junction: {entry.path}")
                if callback:
                    callback(entry, False)
                continue

            measured = None if self._platform is None else measure_files(entry.path, self._platform)
            size_bytes = entry.size_bytes if measured is None else reclaimable_allocation(measured.values())
            if not self._still_offered(entry):
                _logger.warning("Refusing to delete what is no longer confirmed as junk: %s", entry.path)
                skipped += 1
                errors.append(f"Skipped, no longer confirmed as junk: {entry.path}")
                if callback:
                    callback(entry, False)
                continue

            failure = None if self._dry_run else self._try_delete(entry.path)
            if failure is None:
                _logger.info(
                    "%s: %s (%d bytes)", "Dry run, would remove" if self._dry_run else "Removed", entry.path, size_bytes
                )
                deleted += 1
                bytes_removed += size_bytes
                removed_paths.add(entry.path)
            else:
                _logger.error("Failed to delete %s: %s", entry.path, failure)
                skipped += 1
                errors.append(f"{entry.path}: {failure}")
                if measured is not None:
                    bytes_removed += reclaimable_allocation(
                        allocation for file_path, allocation in measured.items() if _is_gone(file_path)
                    )
            if callback:
                callback(entry, failure is None)

        if self._dry_run:
            _logger.info(
                "Dry run complete: would remove %d entries (%d bytes), %d skipped", deleted, bytes_removed, skipped
            )
        else:
            _logger.info(
                "Clean complete: %d deleted, %d skipped, %d bytes %s",
                deleted,
                skipped,
                bytes_removed,
                "moved to trash" if self._use_trash else "freed",
            )
        return CleanStats(
            deleted=deleted,
            skipped=skipped,
            errors=errors,
            bytes_freed=0 if self._use_trash else bytes_removed,
            bytes_trashed=bytes_removed if self._use_trash else 0,
        )

    def _try_delete(self, path: Path) -> Exception | None:
        try:
            self._delete(path)
        except (OSError, RuntimeError) as error:
            return error
        return None

    def _delete(self, path: Path) -> None:
        """Delete path, checking once more that it is not a reparse point.

        clean() filters reparse points while iterating, but the path can be swapped for a symlink or
        junction before this call (TOCTOU). Checking again right before the destructive call narrows that
        window without closing it, and only the final path component is checked. shutil.rmtree alone
        would not refuse a Windows junction at the top level (it only rejects symlinks via os.path.islink).
        """
        if is_reparse_point(path):
            raise RuntimeError(f"Path became a reparse point before deletion: {path}")
        if self._use_trash:
            send2trash(str(path))
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
