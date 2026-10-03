import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

POSIX_BLOCK_BYTES: Final = 512


@dataclass(frozen=True, slots=True, kw_only=True)
class FileAllocation:
    """What one file occupies on disk and how many names point at it."""

    allocated_bytes: int
    file_id: tuple[int, int]
    link_count: int


class PlatformAdapter(abc.ABC):
    """OS abstraction for registry, well-known directories and on-disk file sizes, injected into clients."""

    @abc.abstractmethod
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        """Read a string value from the platform registry (Windows-only concept)."""

    @abc.abstractmethod
    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        """List subkey names under a registry path."""

    @abc.abstractmethod
    def has_registry(self) -> bool:
        """Return whether the platform has a registry that read_registry_dword can read."""

    @abc.abstractmethod
    def read_registry_dword(self, key: str, subkey: str, value_name: str) -> int | None:
        """Read a DWORD from the 32-bit registry view. None when no such DWORD can be read.

        That view is where Steam's install-script records were observed. That Steam consults it is assumed.
        """

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

    def file_allocation(self, path: Path) -> FileAllocation:
        """Return the disk space a file holds, without following a symlink.

        The default reads POSIX `st_blocks`, which already reflects sparse and compressed files.

        Raises:
            OSError: The file cannot be inspected.
        """
        file_stat = path.lstat()
        return FileAllocation(
            allocated_bytes=file_stat.st_blocks * POSIX_BLOCK_BYTES,
            file_id=(file_stat.st_dev, file_stat.st_ino),
            link_count=file_stat.st_nlink,
        )

    def wine_prefixes(self) -> list[Path]:  # pragma: no cover - default only used by WindowsAdapter
        """Return discovered Wine/Proton drive_c paths. Empty on Windows."""
        return []
