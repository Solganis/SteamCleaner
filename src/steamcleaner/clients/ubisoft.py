import logging
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import scan_game, scan_launcher_logs
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs

_logger = logging.getLogger(__name__)

_REGISTRY_LAUNCHER_PATH = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher"
_REGISTRY_INSTALLS_PATH = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"


@ClientRegistry.register
class UbisoftClient(GameClient):
    @property
    def name(self) -> str:
        return "Ubisoft Connect"

    def is_installed(self) -> bool:
        launcher_dir = self._launcher_install_dir()
        if launcher_dir is not None:
            _logger.debug("Ubisoft Connect detected via registry: %s", launcher_dir)
            return True
        if self._appdata_dir().is_dir():
            _logger.debug("Ubisoft Connect detected via appdata: %s", self._appdata_dir())
            return True
        for prefix in self._platform.wine_prefixes():
            for program_dir_name in ("Program Files (x86)", "Program Files"):
                launcher = prefix / program_dir_name / "Ubisoft" / "Ubisoft Game Launcher"
                if launcher.is_dir():
                    _logger.debug("Ubisoft Connect detected via Wine prefix: %s", launcher)
                    return True
        return False

    def _launcher_install_dir(self) -> Path | None:
        install_dir = self._platform.read_registry_str("HKLM", _REGISTRY_LAUNCHER_PATH, "InstallDir")
        if install_dir:
            candidate = Path(install_dir)
            if candidate.is_dir():
                return candidate
        return None

    def _appdata_dir(self) -> Path:
        return self._platform.appdata_local() / "Ubisoft Game Launcher"

    def game_install_paths(self) -> list[Path]:
        paths: list[Path] = []

        for game_id in self._platform.list_registry_subkeys("HKLM", _REGISTRY_INSTALLS_PATH):
            install_dir = self._platform.read_registry_str(
                "HKLM", rf"{_REGISTRY_INSTALLS_PATH}\{game_id}", "InstallDir"
            )
            if install_dir:
                candidate = Path(install_dir)
                if candidate.is_dir() and candidate not in paths:
                    paths.append(candidate)

        launcher_dir = self._launcher_install_dir()
        if launcher_dir:
            games_dir = launcher_dir / "games"
            if games_dir.is_dir():
                for game_dir in list_subdirs(games_dir):
                    if game_dir not in paths:
                        paths.append(game_dir)

        for prefix in self._platform.wine_prefixes():
            for program_dir_name in ("Program Files (x86)", "Program Files"):
                games_dir = prefix / program_dir_name / "Ubisoft" / "Ubisoft Game Launcher" / "games"
                if games_dir.is_dir():
                    for game_dir in list_subdirs(games_dir):
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
        yield from self._scan_launcher_cache()
        yield from self._scan_launcher_crashes()
        yield from self._scan_launcher_logs()
        yield from self._scan_appdata_logs()

    def _scan_launcher_cache(self) -> Iterator[JunkEntry]:
        launcher_dir = self._launcher_install_dir()
        if not launcher_dir:
            return
        cache_dir = launcher_dir / "cache"
        if not cache_dir.is_dir() or self.cancelled:
            return
        total = dir_size(cache_dir)
        if total > 0:
            yield JunkEntry(
                path=cache_dir,
                category=JunkCategory.SHADER_CACHE,
                size_bytes=total,
                client_name=self.name,
                description="Ubisoft Connect cache",
                game_root=launcher_dir,
            )

    def _scan_launcher_crashes(self) -> Iterator[JunkEntry]:
        launcher_dir = self._launcher_install_dir()
        if not launcher_dir:
            return
        crashes_dir = launcher_dir / "crashes"
        if not crashes_dir.is_dir() or self.cancelled:
            return
        total = dir_size(crashes_dir)
        if total > 0:
            yield JunkEntry(
                path=crashes_dir,
                category=JunkCategory.CRASH_DUMP,
                size_bytes=total,
                client_name=self.name,
                description="Ubisoft Connect crash dumps",
                game_root=launcher_dir,
            )

    def _scan_launcher_logs(self) -> Iterator[JunkEntry]:
        launcher_dir = self._launcher_install_dir()
        if not launcher_dir:
            return
        yield from scan_launcher_logs(
            [launcher_dir / "logs"],
            self.name,
            lambda: self.cancelled,
            "Ubisoft Connect launcher log",
        )

    def _scan_appdata_logs(self) -> Iterator[JunkEntry]:
        yield from scan_launcher_logs(
            [self._appdata_dir() / "logs"],
            self.name,
            lambda: self.cancelled,
            "Ubisoft Connect launcher log",
        )
