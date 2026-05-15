import logging
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import scan_game
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import dir_size, list_subdirs
from steamcleaner.utils.vdf import load_vdf

_logger = logging.getLogger(__name__)


def parse_library_folders_vdf(path: Path) -> list[Path]:
    """Parse libraryfolders.vdf to extract library paths."""
    data = load_vdf(path)
    folders = data.get("libraryfolders", {})
    paths: list[Path] = []
    if isinstance(folders, dict):
        for entry in folders.values():
            if isinstance(entry, dict):
                raw_path = entry.get("path", "")
            elif isinstance(entry, str):
                raw_path = entry
            else:
                continue
            if raw_path:
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
        """Parse config/config.vdf for BaseInstallFolder_N keys (legacy Steam)."""
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
        for game_dir in list_subdirs(common):
            if self.cancelled:
                return
            yield from scan_game(game_dir, self.name, lambda: self.cancelled)

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
                display = f"{app_name} (shader cache)" if app_name else f"Steam shader cache (appid {app_dir.name})"
                yield JunkEntry(
                    path=app_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=size,
                    client_name=self.name,
                    description=display,
                    game_root=library,
                    display_name=display,
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
                game_root=install,
            )
