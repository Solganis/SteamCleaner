import logging
import shutil
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from steamcleaner.models.junk import GUARDED_CATEGORIES, JunkEntry
from steamcleaner.platform import create_adapter
from steamcleaner.platform.base import TrashRefusedError
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import is_gone, is_reparse_point, measure_files, reclaimable_allocation

if TYPE_CHECKING:
    from pathlib import Path

    from steamcleaner.models.scan_result import ScanResult
    from steamcleaner.platform.base import PlatformAdapter

_logger = logging.getLogger(__name__)

CleanCallback = Callable[[JunkEntry, bool], None]


def _stands_unchecked(entry: JunkEntry) -> bool:
    return entry.category not in GUARDED_CATEGORIES


@dataclass(frozen=True, slots=True, kw_only=True)
class _Removal:
    """What became of one entry. for_good: a permanent deletion was started."""

    failure: Exception | None = None
    in_trash: bool = False
    for_good: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanStats:
    """Outcome of a clean, or what a dry run would do.

    trashed counts the deleted entries the trash holds. bytes_trashed stays on disk until the trash is emptied,
    bytes_freed is what was deleted for good. A failed move to the trash adds to neither.
    """

    deleted: int = 0
    trashed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0
    bytes_trashed: int = 0


class CleanEngine:
    def __init__(
        self,
        *,
        use_trash: bool = True,
        dry_run: bool = False,
        exclusions: ExclusionRegistry | None = None,
        platform: PlatformAdapter | None = None,
        still_offered: Callable[[JunkEntry], bool] | None = None,
        delete_for_good: Collection[Path] = (),
    ) -> None:
        self._use_trash = use_trash
        self._dry_run = dry_run
        self._still_offered = _stands_unchecked if still_offered is None else still_offered
        self._delete_for_good = frozenset(delete_for_good)
        # The builtin list by default: a caller that wires no registry still cannot delete a protected path.
        self._exclusions = exclusions or ExclusionRegistry()
        self._platform = platform
        self._trash = platform or create_adapter()

    def clean(self, result: ScanResult, callback: CleanCallback | None = None) -> CleanStats:
        """Delete every entry of result, parents first. A dry run only reports.

        Left alone: an excluded path, a reparse point, an entry still_offered no longer confirms, and one the
        trash refuses unless its path is in delete_for_good. With a platform sizes are measured at deletion,
        without one the adapter of this machine still stands for the trash.
        """
        deleted = 0
        trashed = 0
        skipped = 0
        errors: list[str] = []
        bytes_freed = 0
        bytes_trashed = 0
        went_to_trash: dict[Path, bool] = {}

        def refuse(entry: JunkEntry, reason: str) -> None:
            nonlocal skipped
            _logger.warning("%s: %s", reason, entry.path)
            skipped += 1
            errors.append(f"{reason}: {entry.path}")
            if callback:
                callback(entry, False)

        _logger.info(
            "Starting clean: %d entries, dry_run=%s, use_trash=%s",
            len(result.entries),
            self._dry_run,
            self._use_trash,
        )

        for entry in sorted(result.entries, key=lambda entry: len(entry.path.parts)):
            holder = next((path for path in (entry.path, *entry.path.parents) if path in went_to_trash), None)
            if holder is not None:
                _logger.debug("Already removed with an earlier entry: %s", entry.path)
                deleted += 1
                trashed += went_to_trash[holder]
                if callback:
                    callback(entry, True)
                continue

            if is_gone(entry.path):
                _logger.debug("Path no longer exists, skipping: %s", entry.path)
                skipped += 1
                continue

            if self._exclusions.is_excluded(entry.path):
                refuse(entry, "Skipped protected path")
                continue

            if is_reparse_point(entry.path):
                refuse(entry, "Skipped symlink/junction")
                continue

            measured = None if self._platform is None else measure_files(entry.path, self._platform)
            size_bytes = entry.size_bytes if measured is None else reclaimable_allocation(measured.values())
            if not self._still_offered(entry):
                refuse(entry, "Skipped, no longer confirmed as junk")
                continue

            removal = self._forecast(entry.path, size_bytes) if self._dry_run else self._try_remove(entry.path)
            failure, in_trash = removal.failure, removal.in_trash
            if isinstance(failure, TrashRefusedError):
                refuse(entry, "Skipped, the trash would not keep it")
                continue

            if failure is None:
                _logger.info(
                    "%s: %s (%d bytes)", "Dry run, would remove" if self._dry_run else "Removed", entry.path, size_bytes
                )
                deleted += 1
                trashed += in_trash
                removed_bytes = size_bytes
                went_to_trash[entry.path] = in_trash
            else:
                _logger.error("Failed to delete %s: %s", entry.path, failure)
                skipped += 1
                errors.append(f"{entry.path}: {failure}")
                removed_bytes = (
                    0
                    if measured is None or not removal.for_good
                    else reclaimable_allocation(
                        allocation for file_path, allocation in measured.items() if is_gone(file_path)
                    )
                )
            if in_trash:
                bytes_trashed += removed_bytes
            else:
                bytes_freed += removed_bytes
            if callback:
                callback(entry, failure is None)

        _logger.info(
            "%s: %d entries, %d skipped, %d bytes moved to trash, %d bytes freed",
            "Dry run complete, would remove" if self._dry_run else "Clean complete",
            deleted,
            skipped,
            bytes_trashed,
            bytes_freed,
        )
        return CleanStats(
            deleted=deleted,
            trashed=trashed,
            skipped=skipped,
            errors=errors,
            bytes_freed=bytes_freed,
            bytes_trashed=bytes_trashed,
        )

    def _forecast(self, path: Path, size_bytes: int) -> _Removal:
        if not self._use_trash:
            return _Removal(for_good=True)
        if self._trash.keeps_trash(path, size_bytes):
            return _Removal(in_trash=True)
        if path in self._delete_for_good:
            return _Removal(for_good=True)
        return _Removal(failure=TrashRefusedError())

    def _try_remove(self, path: Path) -> _Removal:
        """Offer path to the trash or delete it for good. The reparse check is repeated: a link may replace it."""
        if is_reparse_point(path):
            return _Removal(failure=RuntimeError(f"Path became a reparse point before deletion: {path}"))
        if self._use_trash:
            try:
                return _Removal(in_trash=self._trash.send_to_trash(path))
            except TrashRefusedError as refusal:
                if path not in self._delete_for_good:
                    return _Removal(failure=refusal)
            except OSError as error:
                return _Removal(failure=error)
        try:
            self._delete(path)
        except OSError as error:
            return _Removal(failure=error, for_good=True)
        return _Removal(for_good=True)

    @staticmethod
    def _delete(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
