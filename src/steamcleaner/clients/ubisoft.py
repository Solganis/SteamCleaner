import logging
import re
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs, walk_files

_logger = logging.getLogger(__name__)

_REDIST_DIR_RE = re.compile(r"(directx|redist|_commonredist|miles|support|installer)", re.IGNORECASE)
_JUNK_EXTENSIONS = frozenset({".cab", ".exe", ".msi", ".so", ".dll"})
_DUMP_EXTENSIONS = frozenset({".dmp", ".mdmp"})
_LOG_MIN_SIZE = 1024 * 1024
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
            yield from self._scan_game(game_dir)

        if self.cancelled:
            return
        yield from self._scan_launcher_cache()
        yield from self._scan_launcher_crashes()
        yield from self._scan_launcher_logs()
        yield from self._scan_appdata_logs()

    def _scan_game(self, game_dir: Path) -> Iterator[JunkEntry]:
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
            )

    def _scan_launcher_logs(self) -> Iterator[JunkEntry]:
        launcher_dir = self._launcher_install_dir()
        if not launcher_dir:
            return
        logs_dir = launcher_dir / "logs"
        if not logs_dir.is_dir():
            return
        for file_path, size in walk_files(logs_dir):
            if self.cancelled:
                return
            if file_path.suffix.lower() == ".log" and size >= _LOG_MIN_SIZE:
                yield JunkEntry(
                    path=file_path,
                    category=JunkCategory.OLD_LOG,
                    size_bytes=size,
                    client_name=self.name,
                    description="Ubisoft Connect launcher log",
                )

    def _scan_appdata_logs(self) -> Iterator[JunkEntry]:
        logs_dir = self._appdata_dir() / "logs"
        if not logs_dir.is_dir():
            return
        for file_path, size in walk_files(logs_dir):
            if self.cancelled:
                return
            if file_path.suffix.lower() == ".log" and size >= _LOG_MIN_SIZE:
                yield JunkEntry(
                    path=file_path,
                    category=JunkCategory.OLD_LOG,
                    size_bytes=size,
                    client_name=self.name,
                    description="Ubisoft Connect launcher log",
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
