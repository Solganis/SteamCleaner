import re
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import dir_size, list_subdirs, walk_files

_REDIST_DIR_RE = re.compile(r"(directx|redist|_commonredist|miles|support|installer)", re.IGNORECASE)
_JUNK_EXTENSIONS = frozenset({".cab", ".exe", ".msi", ".so", ".dll"})
_DUMP_EXTENSIONS = frozenset({".dmp", ".mdmp"})
_LOG_MIN_SIZE = 1024 * 1024


def _parse_library_folders_vdf(path: Path) -> list[Path]:
    """Parse libraryfolders.vdf to extract library paths."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    paths: list[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        library_path = Path(match.group(1).replace("\\\\", "\\"))
        if library_path.is_dir():
            paths.append(library_path)
    return paths


@ClientRegistry.register
class SteamClient(GameClient):
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry):
        super().__init__(platform, exclusions)
        self._install_path: Path | None = None

    @property
    def name(self) -> str:
        return "Steam"

    def _find_install_path(self) -> Path | None:
        if self._install_path is not None:
            return self._install_path
        for subkey in (
            r"SOFTWARE\Wow6432Node\Valve\Steam",
            r"SOFTWARE\Valve\Steam",
        ):
            registry_value = self._platform.read_registry_str("HKLM", subkey, "InstallPath")
            if registry_value:
                candidate_path = Path(registry_value)
                if candidate_path.is_dir():
                    self._install_path = candidate_path
                    return candidate_path
        for candidate in self._fallback_steam_paths():
            if candidate.is_dir() and (candidate / "steamapps").is_dir():
                self._install_path = candidate
                return candidate
        return None

    def _fallback_steam_paths(self) -> list[Path]:
        home = self._platform.home()
        data_home = self._platform.appdata_local()
        return [
            home / ".steam" / "steam",
            data_home / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            Path("/snap/steam/common/.steam/steam"),
        ]

    def is_installed(self) -> bool:
        return self._find_install_path() is not None

    def _library_folders(self) -> list[Path]:
        install = self._find_install_path()
        if not install:
            return []
        vdf_path = install / "steamapps" / "libraryfolders.vdf"
        folders = _parse_library_folders_vdf(vdf_path)
        if install not in folders:
            folders.insert(0, install)
        return folders

    def scan_junk(self) -> Iterator[JunkEntry]:
        for library in self._library_folders():
            if self.cancelled:
                return
            yield from self._scan_common(library)
            if self.cancelled:
                return
            yield from self._scan_shader_cache(library)

        install = self._find_install_path()
        if install:
            if self.cancelled:
                return
            yield from self._scan_steam_dumps(install)

    def _scan_common(self, library: Path) -> Iterator[JunkEntry]:
        common = library / "steamapps" / "common"
        if not common.is_dir():
            return
        for game_dir in list_subdirs(common):
            if self.cancelled:
                return
            yield from self._scan_game(game_dir)

    def _scan_game(self, game_dir: Path) -> Iterator[JunkEntry]:
        """Single-pass scan of a game directory for redist, dumps, and logs."""
        found_redist: list[Path] = []
        for file_path, size in walk_files(game_dir):
            if self.cancelled:
                return
            extension = file_path.suffix.lower()

            if extension in _DUMP_EXTENSIONS and size > 0:
                yield JunkEntry(
                    path=file_path,
                    category=JunkCategory.CRASH_DUMP,
                    size_bytes=size,
                    client_name=self.name,
                    description=f"Crash dump in {game_dir.name}",
                )
                continue

            if extension == ".log" and size >= _LOG_MIN_SIZE:
                yield JunkEntry(
                    path=file_path,
                    category=JunkCategory.OLD_LOG,
                    size_bytes=size,
                    client_name=self.name,
                    description=f"Log file in {game_dir.name}",
                )
                continue

            if extension in _JUNK_EXTENSIONS and _has_redist_ancestor(file_path, game_dir):
                redist_dir = _find_redist_root(file_path, game_dir)
                if redist_dir and not any(redist_dir.is_relative_to(existing) for existing in found_redist):
                    junk_size = sum(
                        file_size
                        for file_item, file_size in walk_files(redist_dir)
                        if file_item.suffix.lower() in _JUNK_EXTENSIONS
                    )
                    if junk_size > 0:
                        found_redist.append(redist_dir)
                        rel = redist_dir.relative_to(game_dir)
                        yield JunkEntry(
                            path=redist_dir,
                            category=JunkCategory.REDISTRIBUTABLE,
                            size_bytes=junk_size,
                            client_name=self.name,
                            description=f"{game_dir.name}/{rel}",
                        )

    def _scan_shader_cache(self, library: Path) -> Iterator[JunkEntry]:
        shader_cache = library / "steamapps" / "shadercache"
        if not shader_cache.is_dir():
            return
        for app_dir in list_subdirs(shader_cache):
            if self.cancelled:
                return
            size = dir_size(app_dir)
            if size > 0:
                yield JunkEntry(
                    path=app_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=size,
                    client_name=self.name,
                    description=f"Shader cache (appid {app_dir.name})",
                )

    def _scan_steam_dumps(self, install: Path) -> Iterator[JunkEntry]:
        dumps_dir = install / "dumps"
        if not dumps_dir.is_dir() or self.cancelled:
            return
        total = dir_size(dumps_dir)
        if total > 0:
            yield JunkEntry(
                path=dumps_dir,
                category=JunkCategory.CRASH_DUMP,
                size_bytes=total,
                client_name=self.name,
                description="Steam client crash dumps",
            )


def _has_redist_ancestor(file_path: Path, root: Path) -> bool:
    current = file_path.parent
    while current != root:
        if _REDIST_DIR_RE.search(current.name):
            return True
        current = current.parent
    return False


def _find_redist_root(file_path: Path, root: Path) -> Path | None:
    current = file_path.parent
    topmost = None
    while current != root:
        if _REDIST_DIR_RE.search(current.name):
            topmost = current
        current = current.parent
    return topmost
