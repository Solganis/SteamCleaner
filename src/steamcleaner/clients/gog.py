import logging
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import LOG_MIN_SIZE, scan_game
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs, walk_files

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
        home = self._platform.home()
        for logs_dir in (
            self._galaxy_data_dir() / "logs",
            home / "Library" / "Logs" / "GOG.com" / "Galaxy",
        ):
            if not logs_dir.is_dir():
                continue
            for file_path, size in walk_files(logs_dir):
                if self.cancelled:
                    return
                if file_path.suffix.lower() == ".log" and size >= LOG_MIN_SIZE:
                    yield JunkEntry(
                        path=file_path,
                        category=JunkCategory.OLD_LOG,
                        size_bytes=size,
                        client_name=self.name,
                        description="GOG Galaxy launcher log",
                    )

    def _scan_crashdumps(self) -> Iterator[JunkEntry]:
        crashdumps_dir = self._galaxy_data_dir() / "crashdumps"
        if not crashdumps_dir.is_dir() or self.cancelled:
            return
        total = dir_size(crashdumps_dir)
        if total > 0:
            yield JunkEntry(
                path=crashdumps_dir,
                category=JunkCategory.CRASH_DUMP,
                size_bytes=total,
                client_name=self.name,
                description="GOG Galaxy crash dumps",
            )

    def _scan_webcache(self) -> Iterator[JunkEntry]:
        cache_dirs = [self._galaxy_data_dir() / "webcache"]
        home = self._platform.home()
        for bundle_id in ("com.gog.galaxy", "5b6cd92d.com.gog.galaxy"):
            cache_dirs.append(home / "Library" / "Caches" / bundle_id)

        for webcache_dir in cache_dirs:
            if not webcache_dir.is_dir() or self.cancelled:
                continue
            total = dir_size(webcache_dir)
            if total > 0:
                yield JunkEntry(
                    path=webcache_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=total,
                    client_name=self.name,
                    description="GOG Galaxy web cache",
                )
