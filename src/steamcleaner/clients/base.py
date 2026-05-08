from __future__ import annotations

import abc
from collections.abc import Iterator

from steamcleaner.models.junk import JunkEntry
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry


class GameClient(abc.ABC):
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry):
        self._platform = platform
        self._exclusions = exclusions

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @abc.abstractmethod
    def is_installed(self) -> bool:
        ...

    @abc.abstractmethod
    def scan_junk(self) -> Iterator[JunkEntry]:
        """Yield all junk entries without exclusion filtering."""

    def scan_safe(self) -> Iterator[JunkEntry]:
        """Yield junk entries that are not excluded."""
        for entry in self.scan_junk():
            if not self._exclusions.is_excluded(entry.path):
                yield entry
