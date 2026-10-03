import logging
import math
import stat
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import scan_cache_dir, scan_game
from steamcleaner.clients.steam_scripts import InstallerEvidence, collect_installer_evidence, read_install_dir
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs, walk_files
from steamcleaner.utils.vdf import load_vdf

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import date

    from steamcleaner.platform.base import PlatformAdapter
    from steamcleaner.scanner.exclusions import ExclusionRegistry

_logger = logging.getLogger(__name__)

_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def _identify(directory: Path) -> tuple[int, int] | None:
    """Return what a directory is on disk with links followed, or None when nothing is there."""
    try:
        directory_stat = directory.stat()
    except FileNotFoundError:
        return None
    return directory_stat.st_dev, directory_stat.st_ino


def _read_day(file_time: float) -> date | None:
    """Return the UTC day of a file time, or None when it lies past what a calendar holds."""
    try:
        return (_EPOCH + timedelta(seconds=math.floor(file_time))).date()
    except OverflowError:
        return None


def parse_library_folders_vdf(path: Path) -> list[Path]:
    data = load_vdf(path)
    folders = data.get("libraryfolders", {})
    paths: list[Path] = []
    if isinstance(folders, dict):
        for entry in folders.values():
            match entry:
                case {"path": str(raw_path)} | str(raw_path) if raw_path:
                    library_path = Path(raw_path)
                    if library_path.is_dir():
                        paths.append(library_path)
    return paths


@ClientRegistry.register
class SteamClient(GameClient):
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry) -> None:
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
                    _logger.debug("Steam install path from registry: %s", candidate_path)
                    self._install_path = candidate_path
                    return candidate_path
        for candidate in self._fallback_steam_paths():
            if candidate.is_dir() and (candidate / "steamapps").is_dir():
                _logger.debug("Steam install path from fallback: %s", candidate)
                self._install_path = candidate
                return candidate
        _logger.debug("Steam install path not found")
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
        _logger.debug("Parsing libraryfolders.vdf: %s", vdf_path)
        folders = parse_library_folders_vdf(vdf_path)
        if len(folders) <= 1:
            fallback = self._parse_config_vdf_fallback(install)
            for folder in fallback:
                if folder not in folders:
                    folders.append(folder)
        if install not in folders:
            folders.insert(0, install)
        _logger.debug("Found %d library folders: %s", len(folders), [str(folder) for folder in folders])
        return folders

    @staticmethod
    def _parse_config_vdf_fallback(install: Path) -> list[Path]:
        config_path = install / "config" / "config.vdf"
        data = load_vdf(config_path)
        store = data.get("InstallConfigStore", {})
        if not isinstance(store, dict):
            return []
        software = store.get("Software", store.get("software", {}))
        if not isinstance(software, dict):
            return []
        valve = software.get("Valve", software.get("valve", {}))
        if not isinstance(valve, dict):
            return []
        steam_section = valve.get("Steam", valve.get("steam", {}))
        if not isinstance(steam_section, dict):
            return []
        paths: list[Path] = []
        for key, value in steam_section.items():
            if key.lower().startswith("baseinstallfolder_") and isinstance(value, str) and value:
                candidate = Path(value)
                if candidate.is_dir():
                    paths.append(candidate)
        return paths

    def game_install_paths(self) -> list[Path]:
        paths: list[Path] = []
        for library in self._library_folders():
            common = library / "steamapps" / "common"
            if common.is_dir():
                paths.extend(list_subdirs(common))
        return paths

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
        evidence = collect_installer_evidence(library, self._platform)
        leftovers = self._find_leftover_games(library)
        for game_dir in list_subdirs(common):
            if self.cancelled:
                return
            found: list[Path] = []
            for entry in scan_game(game_dir, self.name, lambda: self.cancelled):
                if evidence.protects(entry.path):
                    _logger.info("Kept, an install script of Steam may still need it: %s", entry.path)
                    continue
                found.append(entry.path)
                yield entry
            yield from self._scan_finished_installers(game_dir, evidence, found)
            if game_dir.name in leftovers:
                yield from self._scan_leftover(game_dir)

    @staticmethod
    def _find_leftover_games(library: Path) -> set[str]:
        """Return the names of the game directories of a library that no app manifest describes.

        None when that cannot be told: no manifest, one that names no one game, or a directory that cannot be
        identified. Directories are matched by what they are on disk. Names are returned, not paths: paths that
        differ in letter case compare equal on Windows.
        """
        described: list[Path] = []
        for manifest_path in (library / "steamapps").glob("appmanifest_*.acf"):
            install_dir = read_install_dir(manifest_path, library)
            if install_dir is None:
                return set()
            described.append(install_dir)
        if not described:
            return set()
        try:
            listed = Counter(list_subdirs(library / "steamapps" / "common"))
            owned = {_identify(install_dir) for install_dir in described}
            return {
                game_dir.name for game_dir, count in listed.items() if count == 1 and _identify(game_dir) not in owned
            }
        except OSError:
            return set()

    def still_offers(self, entry: JunkEntry) -> bool:
        """Work out the leftovers of the library again. What the folder holds is not read again."""
        if entry.category is not JunkCategory.LEFTOVER:
            return True
        return entry.path.name in self._find_leftover_games(entry.path.parents[2])

    def _scan_leftover(self, game_dir: Path) -> Iterator[JunkEntry]:
        """Yield the directory of an uninstalled game, unless it holds no bytes or has a Steam library inside."""
        size = 0
        last_written = -math.inf
        for file_path, _ in walk_files(game_dir):
            if self.cancelled:
                return
            if file_path.match("steamapps/appmanifest_*.acf"):
                _logger.info("Kept, it holds a Steam library of its own: %s", game_dir)
                return
            try:
                file_stat = file_path.lstat()
            except OSError:
                continue
            size += file_stat.st_size
            last_written = max(last_written, file_stat.st_mtime)
        if size == 0:
            return
        day = _read_day(last_written)
        written = "an unknown date" if day is None else day.isoformat()
        yield JunkEntry(
            path=game_dir,
            category=JunkCategory.LEFTOVER,
            size_bytes=size,
            client_name=self.name,
            description=f"Left by an uninstalled game, last written on {written}",
            game_root=game_dir,
            display_name=game_dir.name,
            last_written=day,
        )

    def _scan_finished_installers(
        self, game_dir: Path, evidence: InstallerEvidence, found: list[Path]
    ) -> Iterator[JunkEntry]:
        """Yield the installers whose install steps are all recorded as complete, unless already found."""
        for installer, step_name in evidence.finished.items():
            if game_dir not in installer.parents or not {installer, *installer.parents}.isdisjoint(found):
                continue
            try:
                installer_stat = installer.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(installer_stat.st_mode):
                continue
            yield JunkEntry(
                path=installer,
                category=JunkCategory.INSTALLER,
                size_bytes=installer_stat.st_size,
                client_name=self.name,
                description=f"Installer in {game_dir.name}, Steam install step recorded as complete ({step_name})",
                game_root=game_dir,
            )

    @staticmethod
    def _build_appid_map(library: Path) -> dict[str, str]:
        steamapps = library / "steamapps"
        appid_map: dict[str, str] = {}
        for manifest in steamapps.glob("appmanifest_*.acf"):
            data = load_vdf(manifest)
            app_state = data.get("AppState", {})
            if isinstance(app_state, dict):
                appid = app_state.get("appid", "")
                name = app_state.get("name", "")
                if isinstance(appid, str) and isinstance(name, str) and appid and name:
                    appid_map[appid] = name
        return appid_map

    def _scan_shader_cache(self, library: Path) -> Iterator[JunkEntry]:
        shader_cache = library / "steamapps" / "shadercache"
        if not shader_cache.is_dir():
            return
        appid_map = self._build_appid_map(library)
        for app_dir in list_subdirs(shader_cache):
            if self.cancelled:
                return
            size = dir_size(app_dir)
            if size > 0:
                app_name = appid_map.get(app_dir.name)
                appid = f"appid {app_dir.name}"
                yield JunkEntry(
                    path=app_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=size,
                    client_name=self.name,
                    description=f"Steam shader cache of {app_name or appid}",
                    game_root=library,
                    display_name=app_name or appid,
                )

    def _scan_steam_dumps(self, install: Path) -> Iterator[JunkEntry]:
        yield from scan_cache_dir(
            install / "dumps",
            JunkCategory.CRASH_DUMP,
            self.name,
            "Steam client crash dumps",
            lambda: self.cancelled,
            game_root=install,
        )
