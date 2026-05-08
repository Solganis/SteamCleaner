from __future__ import annotations

from collections.abc import Callable

from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry

ProgressCallback = Callable[[str, int], None]


class ScanEngine:
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry | None = None):
        self._platform = platform
        self._exclusions = exclusions or ExclusionRegistry()

    def scan(self, progress: ProgressCallback | None = None) -> ScanResult:
        all_entries: list[JunkEntry] = []
        clients = list(ClientRegistry.create_all(self._platform, self._exclusions))

        for client in clients:
            if not client.is_installed():
                if progress:
                    progress(f"{client.name}: not installed", 0)
                continue

            if progress:
                progress(f"Scanning {client.name}...", 0)

            count = 0
            for entry in client.scan_safe():
                all_entries.append(entry)
                count += 1

            if progress:
                progress(f"{client.name}: found {count} items", count)

        return ScanResult(entries=all_entries)
