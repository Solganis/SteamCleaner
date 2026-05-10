import logging
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.scanner.patterns import COMMON_PATTERNS
from steamcleaner.utils.fs import list_subdirs, walk_files

_logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int], None]
FoundCallback = Callable[[JunkEntry], None]


class ScanEngine:
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry | None = None):
        self._platform = platform
        self._exclusions = exclusions or ExclusionRegistry()

    def scan(
        self,
        progress: ProgressCallback | None = None,
        on_found: FoundCallback | None = None,
        cancel: threading.Event | None = None,
        custom_paths: list[Path] | None = None,
    ) -> ScanResult:
        all_entries: list[JunkEntry] = []
        clients = list(ClientRegistry.create_all(self._platform, self._exclusions))
        _logger.info("Starting scan with %d registered clients", len(clients))

        for client in clients:
            if cancel and cancel.is_set():
                break

            if not client.is_installed():
                _logger.info("%s: not installed, skipping", client.name)
                if progress:
                    progress(f"{client.name}: not installed", len(all_entries))
                continue

            _logger.info("%s: installed, scanning", client.name)
            if progress:
                progress(f"Scanning {client.name}...", len(all_entries))

            count_before = len(all_entries)
            for entry in client.scan_safe(cancel=cancel):
                if cancel and cancel.is_set():
                    break
                all_entries.append(entry)
                if on_found:
                    on_found(entry)
                if progress:
                    progress(f"Scanning {client.name}... ({len(all_entries)} found)", len(all_entries))
            _logger.info("%s: found %d entries", client.name, len(all_entries) - count_before)

        if custom_paths:
            for custom_path in custom_paths:
                if cancel and cancel.is_set():
                    break
                if not custom_path.is_dir():
                    _logger.debug("Custom path does not exist: %s", custom_path)
                    continue
                _logger.info("Scanning custom path: %s", custom_path)
                if progress:
                    progress(f"Scanning {custom_path.name}...", len(all_entries))
                for entry in self._scan_custom_path(custom_path, cancel):
                    all_entries.append(entry)
                    if on_found:
                        on_found(entry)
                    if progress:
                        progress(f"Scanning {custom_path.name}... ({len(all_entries)} found)", len(all_entries))

        _logger.info("Scan complete: %d total entries", len(all_entries))
        return ScanResult(entries=all_entries)

    def _scan_custom_path(self, root: Path, cancel: threading.Event | None = None) -> Iterator[JunkEntry]:
        for game_dir in list_subdirs(root):
            if cancel and cancel.is_set():
                return
            yield from self._scan_game_dir(game_dir, cancel)

    def _scan_game_dir(self, game_dir: Path, cancel: threading.Event | None = None) -> Iterator[JunkEntry]:
        for file_path, size in walk_files(game_dir):
            if cancel and cancel.is_set():
                return

            parent_str = str(file_path.parent)
            extension = file_path.suffix.lower()

            for pattern in COMMON_PATTERNS:
                matches_dir = pattern.dir_regex.search(parent_str)
                matches_ext = not pattern.file_extensions or extension in pattern.file_extensions
                if matches_dir and matches_ext:
                    if self._exclusions.is_excluded(file_path):
                        continue
                    yield JunkEntry(
                        path=file_path,
                        category=pattern.category,
                        size_bytes=size,
                        client_name="Custom",
                        description=pattern.description,
                        game_root=game_dir,
                    )
                    break
