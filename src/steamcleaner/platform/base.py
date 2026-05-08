from __future__ import annotations

import abc
from pathlib import Path


class PlatformAdapter(abc.ABC):
    @abc.abstractmethod
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        """Read a string value from the platform registry (Windows-only concept)."""

    @abc.abstractmethod
    def appdata_local(self) -> Path:
        """Return the local application data directory."""

    @abc.abstractmethod
    def appdata_roaming(self) -> Path:
        """Return the roaming application data directory."""

    @abc.abstractmethod
    def home(self) -> Path:
        """Return the user home directory."""

    @abc.abstractmethod
    def program_files(self) -> list[Path]:
        """Return Program Files directories (or equivalent)."""
