import logging
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import scan_cache_dir, scan_game, scan_launcher_logs
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import list_subdirs

_logger = logging.getLogger(__name__)

_REGISTRY_GAMES_PATH = r"SOFTWARE\WOW6432Node\GOG.com\Games"


@ClientRegistry.register
class GogClient(GameClient):
    @property
    def name(self) -> str:
        return "GOG Galaxy"

    def is_installed(self) -> bool:
        for data_dir in (self._galaxy_data_dir(), self._galaxy_appdata_dir()):
            if data_dir.is_dir():
                _logger.debug("GOG Galaxy detected via %s", data_dir)
                return True
        gog_games = self._platform.home() / "GOG Games"
        if gog_games.is_dir():
            _logger.debug("GOG Galaxy detected via %s", gog_games)
            return True
        for prefix in self._platform.wine_prefixes():
            for gog_path in (
                prefix / "Program Files (x86)" / "GOG Galaxy" / "Games",
                prefix / "GOG Games",
            ):
                if gog_path.is_dir():
                    _logger.debug("GOG Galaxy detected via Wine prefix: %s", gog_path)
                    return True
        return False

    def _galaxy_data_dir(self) -> Path:
        return self._platform.programdata() / "GOG.com" / "Galaxy"

    def _galaxy_appdata_dir(self) -> Path:
        return self._platform.appdata_local() / "GOG.com" / "Galaxy"

    def game_install_paths(self) -> list[Path]:
        paths: list[Path] = []

        for game_id in self._platform.list_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH):
            install_dir = self._platform.read_registry_str("HKLM", rf"{_REGISTRY_GAMES_PATH}\{game_id}", "path")
            if install_dir:
                candidate = Path(install_dir)
                if candidate.is_dir() and candidate not in paths:
                    paths.append(candidate)

        for program_dir in self._platform.program_files():
            for dir_name in ("GOG Galaxy/Games", "GOG Games"):
                games_dir = program_dir / dir_name
                if games_dir.is_dir():
                    for game_dir in list_subdirs(games_dir):
                        if game_dir not in paths:
                            paths.append(game_dir)

        gog_games = self._platform.home() / "GOG Games"
        if gog_games.is_dir():
            for game_dir in list_subdirs(gog_games):
                if game_dir not in paths:
                    paths.append(game_dir)

        for prefix in self._platform.wine_prefixes():
            for gog_path in (
                prefix / "Program Files (x86)" / "GOG Galaxy" / "Games",
                prefix / "GOG Games",
                prefix / "Program Files" / "GOG Games",
            ):
                if gog_path.is_dir():
                    for game_dir in list_subdirs(gog_path):
                        if game_dir not in paths:
                            paths.append(game_dir)

        return paths

    def scan_junk(self) -> Iterator[JunkEntry]:
        for game_dir in self.game_install_paths():
            if self.cancelled:
                return
            yield from scan_game(game_dir, self.name, lambda: self.cancelled)

        if self.cancelled:
            return
        yield from self._scan_launcher_logs()
        yield from self._scan_crashdumps()
        yield from self._scan_webcache()

    def _scan_launcher_logs(self) -> Iterator[JunkEntry]:
        galaxy_dir = self._galaxy_data_dir()
        home = self._platform.home()
        yield from scan_launcher_logs(
            [galaxy_dir / "logs", home / "Library" / "Logs" / "GOG.com" / "Galaxy"],
            self.name,
            lambda: self.cancelled,
            "GOG Galaxy launcher log",
            game_root=galaxy_dir,
        )

    def _scan_crashdumps(self) -> Iterator[JunkEntry]:
        galaxy_dir = self._galaxy_data_dir()
        yield from scan_cache_dir(
            galaxy_dir / "crashdumps",
            JunkCategory.CRASH_DUMP,
            self.name,
            "GOG Galaxy crash dumps",
            lambda: self.cancelled,
            game_root=galaxy_dir,
        )

    def _scan_webcache(self) -> Iterator[JunkEntry]:
        galaxy_dir = self._galaxy_data_dir()
        home = self._platform.home()
        cache_dirs = [
            galaxy_dir / "webcache",
            home / "Library" / "Caches" / "com.gog.galaxy",
            home / "Library" / "Caches" / "5b6cd92d.com.gog.galaxy",
        ]
        for webcache_dir in cache_dirs:
            if self.cancelled:
                return
            yield from scan_cache_dir(
                webcache_dir,
                JunkCategory.SHADER_CACHE,
                self.name,
                "GOG Galaxy web cache",
                lambda: self.cancelled,
                game_root=galaxy_dir,
            )
