from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry

_REDIST_DIR_RE = re.compile(r"(directx|redist|_commonredist|miles|support|installer)", re.IGNORECASE)
_JUNK_EXTENSIONS = frozenset({".cab", ".exe", ".msi", ".so", ".dll"})
_DUMP_EXTENSIONS = frozenset({".dmp", ".mdmp"})
_LOG_MIN_SIZE = 1024 * 1024  # 1 MB


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


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for file_path in path.rglob("*"):
            if file_path.is_file():
                with contextlib.suppress(OSError):
                    total += file_path.stat().st_size
    except OSError:
        pass
    return total


def _file_size(path: Path) -> int:
    with contextlib.suppress(OSError):
        return path.stat().st_size
    return 0


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
        for candidate in self._linux_steam_paths():
            if candidate.is_dir() and (candidate / "steamapps").is_dir():
                self._install_path = candidate
                return candidate
        return None

    def _linux_steam_paths(self) -> list[Path]:
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
            yield from self._scan_steam_logs(install)
            if self.cancelled:
                return
            yield from self._scan_steam_dumps(install)

    def _scan_common(self, library: Path) -> Iterator[JunkEntry]:
        common = library / "steamapps" / "common"
        if not common.is_dir():
            return
        try:
            game_dirs = list(common.iterdir())
        except OSError:
            return
        for game_dir in game_dirs:
            if self.cancelled:
                return
            if not game_dir.is_dir():
                continue
            yield from self._scan_game_redist(game_dir)
            yield from self._scan_game_dumps(game_dir)
            yield from self._scan_game_logs(game_dir)

    def _scan_game_redist(self, game_dir: Path) -> Iterator[JunkEntry]:
        """Recursive scan for redistributable directories, skipping nested matches."""
        found: list[Path] = []
        try:
            for subdir in game_dir.rglob("*"):
                if self.cancelled:
                    return
                if not subdir.is_dir():
                    continue
                if not _REDIST_DIR_RE.search(subdir.name):
                    continue
                if any(subdir.is_relative_to(parent) for parent in found):
                    continue
                junk_files = [
                    file_path for file_path in subdir.rglob("*")
                    if file_path.is_file() and file_path.suffix.lower() in _JUNK_EXTENSIONS
                ]
                if junk_files:
                    size = sum(_file_size(junk_file) for junk_file in junk_files)
                    rel = subdir.relative_to(game_dir)
                    found.append(subdir)
                    yield JunkEntry(
                        path=subdir,
                        category=JunkCategory.REDISTRIBUTABLE,
                        size_bytes=size,
                        client_name=self.name,
                        description=f"{game_dir.name}/{rel}",
                    )
        except OSError:
            return

    def _scan_game_dumps(self, game_dir: Path) -> Iterator[JunkEntry]:
        try:
            for file_path in game_dir.rglob("*"):
                if self.cancelled:
                    return
                if file_path.is_file() and file_path.suffix.lower() in _DUMP_EXTENSIONS:
                    size = _file_size(file_path)
                    if size > 0:
                        yield JunkEntry(
                            path=file_path,
                            category=JunkCategory.CRASH_DUMP,
                            size_bytes=size,
                            client_name=self.name,
                            description=f"Crash dump in {game_dir.name}",
                        )
        except OSError:
            return

    def _scan_game_logs(self, game_dir: Path) -> Iterator[JunkEntry]:
        try:
            for log_file in game_dir.rglob("*.log"):
                if self.cancelled:
                    return
                if log_file.is_file():
                    size = _file_size(log_file)
                    if size >= _LOG_MIN_SIZE:
                        yield JunkEntry(
                            path=log_file,
                            category=JunkCategory.OLD_LOG,
                            size_bytes=size,
                            client_name=self.name,
                            description=f"Log file in {game_dir.name}",
                        )
        except OSError:
            return

    def _scan_shader_cache(self, library: Path) -> Iterator[JunkEntry]:
        shader_cache = library / "steamapps" / "shadercache"
        if not shader_cache.is_dir():
            return
        try:
            for app_dir in shader_cache.iterdir():
                if self.cancelled:
                    return
                if app_dir.is_dir():
                    size = _dir_size(app_dir)
                    if size > 0:
                        yield JunkEntry(
                            path=app_dir,
                            category=JunkCategory.SHADER_CACHE,
                            size_bytes=size,
                            client_name=self.name,
                            description=f"Shader cache (appid {app_dir.name})",
                        )
        except OSError:
            return

    def _scan_steam_logs(self, install: Path) -> Iterator[JunkEntry]:
        logs_dir = install / "logs"
        if not logs_dir.is_dir() or self.cancelled:
            return
        total = _dir_size(logs_dir)
        if total >= _LOG_MIN_SIZE:
            yield JunkEntry(
                path=logs_dir,
                category=JunkCategory.OLD_LOG,
                size_bytes=total,
                client_name=self.name,
                description="Steam client logs",
            )

    def _scan_steam_dumps(self, install: Path) -> Iterator[JunkEntry]:
        dumps_dir = install / "dumps"
        if not dumps_dir.is_dir() or self.cancelled:
            return
        total = _dir_size(dumps_dir)
        if total > 0:
            yield JunkEntry(
                path=dumps_dir,
                category=JunkCategory.CRASH_DUMP,
                size_bytes=total,
                client_name=self.name,
                description="Steam client crash dumps",
            )
