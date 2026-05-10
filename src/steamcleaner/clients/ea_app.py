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
_GAME_DIR_NAMES = ("EA Games", "Origin Games")
_REGISTRY_GAMES_PATH = r"SOFTWARE\WOW6432Node\Origin Games"


@ClientRegistry.register
class EaAppClient(GameClient):
    @property
    def name(self) -> str:
        return "EA App"

    def is_installed(self) -> bool:
        for data_dir in (self._ea_desktop_data_dir(), self._ea_app_data_dir(), self._origin_data_dir()):
            if data_dir.is_dir():
                _logger.debug("EA App detected via %s", data_dir)
                return True
        for prefix in self._platform.wine_prefixes():
            for dir_name in _GAME_DIR_NAMES:
                for program_dir_name in ("Program Files", "Program Files (x86)"):
                    wine_path = prefix / program_dir_name / dir_name
                    if wine_path.is_dir():
                        _logger.debug("EA App detected via Wine prefix: %s", wine_path)
                        return True
        return False

    def _ea_desktop_data_dir(self) -> Path:
        return self._platform.appdata_local() / "Electronic Arts" / "EA Desktop"

    def _ea_app_data_dir(self) -> Path:
        return self._platform.appdata_local() / "Electronic Arts" / "EA app"

    def _origin_data_dir(self) -> Path:
        return self._platform.appdata_local() / "Origin"

    def _game_install_paths(self) -> list[Path]:
        paths: list[Path] = []

        for content_id in self._platform.list_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH):
            install_dir = self._platform.read_registry_str(
                "HKLM", rf"{_REGISTRY_GAMES_PATH}\{content_id}", "Install Dir"
            )
            if install_dir:
                candidate = Path(install_dir)
                if candidate.is_dir() and candidate not in paths:
                    paths.append(candidate)

        for program_dir in self._platform.program_files():
            for dir_name in _GAME_DIR_NAMES:
                games_dir = program_dir / dir_name
                if games_dir.is_dir():
                    for game_dir in list_subdirs(games_dir):
                        if game_dir not in paths:
                            paths.append(game_dir)

        for prefix in self._platform.wine_prefixes():
            for dir_name in _GAME_DIR_NAMES:
                for program_dir_name in ("Program Files", "Program Files (x86)"):
                    games_dir = prefix / program_dir_name / dir_name
                    if games_dir.is_dir():
                        for game_dir in list_subdirs(games_dir):
                            if game_dir not in paths:
                                paths.append(game_dir)

        return paths

    def scan_junk(self) -> Iterator[JunkEntry]:
        for game_dir in self._game_install_paths():
            if self.cancelled:
                return
            yield from self._scan_game(game_dir)

        if self.cancelled:
            return
        yield from self._scan_launcher_logs()
        yield from self._scan_launcher_cache()

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

    def _scan_launcher_logs(self) -> Iterator[JunkEntry]:
        for logs_dir in (
            self._ea_desktop_data_dir() / "Logs",
            self._ea_app_data_dir() / "Logs",
            self._platform.programdata() / "EA Desktop" / "Logs",
        ):
            if not logs_dir.is_dir():
                continue
            for file_path, size in walk_files(logs_dir):
                if self.cancelled:
                    return
                if file_path.suffix.lower() == ".log" and size >= _LOG_MIN_SIZE:
                    yield JunkEntry(
                        path=file_path,
                        category=JunkCategory.OLD_LOG,
                        size_bytes=size,
                        client_name=self.name,
                        description="EA App launcher log",
                    )

    def _scan_launcher_cache(self) -> Iterator[JunkEntry]:
        appdata_local = self._platform.appdata_local()
        for cache_dir_name in ("EADesktop", "EALaunchHelper"):
            if self.cancelled:
                return
            cache_dir = appdata_local / cache_dir_name / "cache"
            if not cache_dir.is_dir():
                continue
            total = dir_size(cache_dir)
            if total > 0:
                yield JunkEntry(
                    path=cache_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=total,
                    client_name=self.name,
                    description=f"{cache_dir_name} cache",
                )

        home = self._platform.home()
        for bundle_id in ("com.ea.Origin", "com.EA.EA-app-Migrator", "Origin", "EA app", "EALaunchHelper"):
            if self.cancelled:
                return
            cache_dir = home / "Library" / "Caches" / bundle_id
            if not cache_dir.is_dir():
                continue
            total = dir_size(cache_dir)
            if total > 0:
                yield JunkEntry(
                    path=cache_dir,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=total,
                    client_name=self.name,
                    description=f"EA App cache ({bundle_id})",
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
