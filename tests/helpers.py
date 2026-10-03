import threading
from pathlib import Path
from typing import TYPE_CHECKING

from steamcleaner.clients.base import GameClient
from steamcleaner.platform.base import FileAllocation, PlatformAdapter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from steamcleaner.models.junk import JunkEntry
    from steamcleaner.scanner.exclusions import ExclusionRegistry


class FakePlatformAdapter(PlatformAdapter):
    def __init__(
        self,
        *,
        install_path: Path | None = None,
        home_dir: Path | None = None,
        program_files_dirs: list[Path] | None = None,
        programdata_dir: Path | None = None,
        wine_prefix_dirs: list[Path] | None = None,
        appdata_local_dir: Path | None = None,
    ):
        self._install_path = install_path
        self._home = home_dir or Path.home()
        self._program_files = program_files_dirs or []
        self._programdata = programdata_dir
        self._wine_prefixes = wine_prefix_dirs or []
        self._appdata_local_override = appdata_local_dir
        self._registry: dict[tuple[str, str, str], str] = {}
        self._registry_subkeys: dict[tuple[str, str], list[str]] = {}
        self._allocated_bytes: dict[Path, int] = {}
        if install_path:
            self._registry[("HKLM", r"SOFTWARE\Wow6432Node\Valve\Steam", "InstallPath")] = str(install_path)

    def set_registry(self, key: str, subkey: str, value_name: str, value: str):
        self._registry[(key, subkey, value_name)] = value

    def set_registry_subkeys(self, key: str, subkey: str, subkeys: list[str]):
        self._registry_subkeys[(key, subkey)] = subkeys

    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        return self._registry.get((key, subkey, value_name))

    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        return self._registry_subkeys.get((key, subkey), [])

    def appdata_local(self) -> Path:
        if self._appdata_local_override:
            return self._appdata_local_override
        return self._home / ".local" / "share"

    def appdata_roaming(self) -> Path:
        return self._home / ".config"

    def home(self) -> Path:
        return self._home

    def program_files(self) -> list[Path]:
        return self._program_files

    def programdata(self) -> Path:
        return self._programdata or self._home / "ProgramData"

    def wine_prefixes(self) -> list[Path]:
        return self._wine_prefixes

    def set_allocated_bytes(self, path: Path, allocated_bytes: int):
        self._allocated_bytes[path] = allocated_bytes

    def file_allocation(self, path: Path) -> FileAllocation:
        """Report the file length as its allocation unless a test set one, so sizes are the same on every OS."""
        file_stat = path.lstat()
        return FileAllocation(
            allocated_bytes=self._allocated_bytes.get(path, file_stat.st_size),
            file_id=(file_stat.st_dev, file_stat.st_ino),
            link_count=file_stat.st_nlink,
        )


class ListedEntriesClient(GameClient):
    """Client whose scan yields the entries it was given and never looks at the cancel flag."""

    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry, entries: list[JunkEntry]) -> None:
        super().__init__(platform, exclusions)
        self._entries = entries

    @property
    def name(self) -> str:
        return "Listed entries"

    def is_installed(self) -> bool:
        return True

    def scan_junk(self) -> Iterator[JunkEntry]:
        yield from self._entries


def build_fake_steam_tree(root: Path, games: dict[str, dict[str, list[str]]]) -> Path:
    """Build a fake Steam directory tree.

    Args:
        root: tmp_path root
        games: {game_name: {subdir_name: [filenames]}}

    Returns:
        Steam install path
    """
    steam = root / "Steam"
    common = steam / "steamapps" / "common"
    common.mkdir(parents=True)
    for game_name, subdirs in games.items():
        game_dir = common / game_name
        game_dir.mkdir()
        for subdir_name, files in subdirs.items():
            subdir = game_dir / subdir_name if subdir_name else game_dir
            subdir.mkdir(parents=True, exist_ok=True)
            for filename in files:
                file_path = subdir / filename
                file_path.write_bytes(b"\x00" * 1024)
    return steam


def scan_with_cancel_already_set(client: GameClient) -> list[JunkEntry]:
    """Run ``scan_safe`` with a cancel event that is set before the scan starts."""
    cancel = threading.Event()
    cancel.set()
    return list(client.scan_safe(cancel=cancel))


def scan_cancelling_after(client: GameClient, should_cancel: Callable[[JunkEntry], bool]) -> list[JunkEntry]:
    """Run ``scan_safe`` and set its cancel event as soon as a received entry matches ``should_cancel``."""
    cancel = threading.Event()
    collected: list[JunkEntry] = []
    for entry in client.scan_safe(cancel=cancel):
        collected.append(entry)
        if should_cancel(entry):
            cancel.set()
    return collected
