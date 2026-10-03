import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from steamcleaner.clients.base import GameClient
from steamcleaner.platform.base import FileAllocation, PlatformAdapter, TrashRefusedError

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterator

    from steamcleaner.models.junk import JunkEntry
    from steamcleaner.scanner.exclusions import ExclusionRegistry
    from steamcleaner.utils.vdf import VdfDict


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
        has_registry: bool = True,
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
        self._registry_dwords: dict[tuple[str, str, str], int] = {}
        self._has_registry = has_registry
        self._trashless_roots: list[Path] = []
        self.trash_holds_what_it_takes = True
        self.trash_capacity: int | None = None
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

    def set_registry_dword(self, key: str, subkey: str, value_name: str, value: int):
        self._registry_dwords[(key, subkey, value_name)] = value

    def has_registry(self) -> bool:
        return self._has_registry

    def read_registry_dword(self, key: str, subkey: str, value_name: str) -> int | None:
        return self._registry_dwords.get((key, subkey, value_name))

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

    def lose_trash_under(self, root: Path):
        self._trashless_roots.append(root)

    def keeps_trash(self, path: Path, size_bytes: int) -> bool:
        fits = self.trash_capacity is None or size_bytes <= self.trash_capacity
        return fits and not any(path.is_relative_to(root) for root in self._trashless_roots)

    def send_to_trash(self, path: Path) -> bool:
        held = [path, *path.rglob("*")] if path.is_dir() else [path]
        length = sum(item.lstat().st_size for item in held if item.is_file())
        if not self.keeps_trash(path, length):
            raise TrashRefusedError("the trash would not keep it")
        super().send_to_trash(path)
        return self.trash_holds_what_it_takes

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


def _escape_vdf_string(raw: str) -> str:
    """Escape backslash, then double quote: the other order would escape the added backslash again."""
    return raw.replace("\\", "\\\\").replace('"', '\\"')


def serialize_vdf(data: VdfDict, indent: int = 0) -> str:
    """Render a nested dict back into VDF text, the inverse of parse_vdf for quoted tokens."""
    padding = "\t" * indent
    lines: list[str] = []
    for key, value in data.items():
        quoted_key = f'"{_escape_vdf_string(key)}"'
        if isinstance(value, dict):
            lines.append(f"{padding}{quoted_key}")
            lines.append(f"{padding}{{")
            nested = serialize_vdf(value, indent + 1)
            if nested:
                lines.append(nested)
            lines.append(f"{padding}}}")
        else:
            lines.append(f'{padding}{quoted_key} "{_escape_vdf_string(value)}"')
    return "\n".join(lines)


def write_app_manifest(library: Path, app_id: int, install_dir: str) -> Path:
    """Write the app manifest Steam keeps for a game installed in a library, and return its path."""
    manifest: VdfDict = {"AppState": {"appid": str(app_id), "name": install_dir, "installdir": install_dir}}
    manifest_path = library / "steamapps" / f"appmanifest_{app_id}.acf"
    manifest_path.write_text(serialize_vdf(manifest), encoding="utf-8")
    return manifest_path


def build_fake_steam_tree(root: Path, games: dict[str, dict[str, list[str]]]) -> Path:
    """Build a fake Steam tree from {game_name: {subdir_name: [filenames]}} and return the install path."""
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


def run_bounded(task: Coroutine[object, object, None], seconds: float = 10) -> None:
    """Run a GUI task to its end. One that does not end fails the test instead of hanging the run."""
    asyncio.run(asyncio.wait_for(task, timeout=seconds))


def scan_with_cancel_already_set(client: GameClient) -> list[JunkEntry]:
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
