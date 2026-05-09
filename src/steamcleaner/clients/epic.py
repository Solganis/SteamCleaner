import json
import re
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs, walk_files

_REDIST_DIR_RE = re.compile(r"(directx|redist|_commonredist|miles|support|installer|prerequisites)", re.IGNORECASE)
_JUNK_EXTENSIONS = frozenset({".cab", ".exe", ".msi", ".so", ".dll"})
_DUMP_EXTENSIONS = frozenset({".dmp", ".mdmp"})
_LOG_MIN_SIZE = 1024 * 1024


@ClientRegistry.register
class EpicClient(GameClient):
    @property
    def name(self) -> str:
        return "Epic Games"

    def is_installed(self) -> bool:
        if any(data_dir.is_dir() for data_dir in self._launcher_data_dirs()):
            return True
        return any((prefix / "Program Files" / "Epic Games").is_dir() for prefix in self._platform.wine_prefixes())

    def _launcher_data_dirs(self) -> list[Path]:
        appdata = self._platform.appdata_local()
        return [
            appdata / "EpicGamesLauncher",
            appdata / "Epic" / "EpicGamesLauncher",
        ]

    def _manifests_dirs(self) -> list[Path]:
        return [
            self._platform.programdata() / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests",
            self._platform.appdata_local() / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests",
        ]

    def _game_install_paths(self) -> list[Path]:
        paths: list[Path] = []

        for manifests_dir in self._manifests_dirs():
            if not manifests_dir.is_dir():
                continue
            for item_file in manifests_dir.iterdir():
                if item_file.suffix == ".item" and item_file.is_file():
                    try:
                        data = json.loads(item_file.read_text(encoding="utf-8", errors="replace"))
                        install_location = data.get("InstallLocation", "")
                        if install_location:
                            candidate = Path(install_location)
                            if candidate.is_dir() and candidate not in paths:
                                paths.append(candidate)
                    except json.JSONDecodeError, OSError:
                        continue

        for program_dir in self._platform.program_files():
            epic_dir = program_dir / "Epic Games"
            if epic_dir.is_dir():
                for game_dir in list_subdirs(epic_dir):
                    if game_dir.name == "Launcher":
                        continue
                    if game_dir not in paths:
                        paths.append(game_dir)

        shared_epic = self._platform.programdata() / "Epic Games"
        if shared_epic.is_dir():
            for game_dir in list_subdirs(shared_epic):
                if game_dir.name == "Launcher":
                    continue
                if game_dir not in paths:
                    paths.append(game_dir)

        for prefix in self._platform.wine_prefixes():
            epic_dir = prefix / "Program Files" / "Epic Games"
            if epic_dir.is_dir():
                for game_dir in list_subdirs(epic_dir):
                    if game_dir.name == "Launcher":
                        continue
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
        yield from self._scan_webcache()

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
        log_dirs = [data_dir / "Saved" / "Logs" for data_dir in self._launcher_data_dirs()]
        log_dirs.append(self._platform.home() / "Library" / "Logs" / "Unreal Engine" / "EpicGamesLauncher")
        for logs_dir in log_dirs:
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
                        description="Epic Games Launcher log",
                    )

    def _scan_webcache(self) -> Iterator[JunkEntry]:
        scanned: set[Path] = set()
        for data_dir in self._launcher_data_dirs():
            saved_dir = data_dir / "Saved"
            if not saved_dir.is_dir():
                continue
            for candidate in saved_dir.iterdir():
                if self.cancelled:
                    return
                if not candidate.is_dir() or not candidate.name.startswith("webcache"):
                    continue
                if candidate in scanned:
                    continue
                scanned.add(candidate)
                total = dir_size(candidate)
                if total > 0:
                    yield JunkEntry(
                        path=candidate,
                        category=JunkCategory.SHADER_CACHE,
                        size_bytes=total,
                        client_name=self.name,
                        description="Epic Games Launcher web cache",
                    )

        macos_cache = self._platform.home() / "Library" / "Caches" / "com.epicgames.EpicGamesLauncher"
        if macos_cache.is_dir() and macos_cache not in scanned:
            total = dir_size(macos_cache)
            if total > 0:
                yield JunkEntry(
                    path=macos_cache,
                    category=JunkCategory.SHADER_CACHE,
                    size_bytes=total,
                    client_name=self.name,
                    description="Epic Games Launcher cache",
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
