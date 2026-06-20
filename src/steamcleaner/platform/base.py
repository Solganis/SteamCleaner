import abc
from pathlib import Path


class PlatformAdapter(abc.ABC):
    """OS abstraction for registry and well-known directory lookups, injected into clients."""

    @abc.abstractmethod
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        """Read a string value from the platform registry (Windows-only concept)."""

    @abc.abstractmethod
    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        """List subkey names under a registry path."""

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

    @abc.abstractmethod
    def programdata(self) -> Path:
        """Return the shared application data directory (ProgramData on Windows)."""

    def wine_prefixes(self) -> list[Path]:
        """Return discovered Wine/Proton drive_c paths. Empty on Windows."""
        return []
