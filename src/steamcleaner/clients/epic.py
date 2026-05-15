import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.registry import ClientRegistry
from steamcleaner.clients.shared import REDIST_DIR_RE, scan_game, scan_launcher_logs
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.utils.fs import dir_size, list_subdirs

_logger = logging.getLogger(__name__)

_EPIC_REDIST_DIR_RE = re.compile(
    REDIST_DIR_RE.pattern + r"|prerequisites",
    re.IGNORECASE,
)


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

    def game_install_paths(self) -> list[Path]:
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
                                _logger.debug("Epic manifest %s -> %s", item_file.name, candidate)
                                paths.append(candidate)
                    except (json.JSONDecodeError, OSError):  # fmt: skip  # flet build bundles Python 3.12
                        _logger.debug("Failed to parse Epic manifest: %s", item_file)
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
        for game_dir in self.game_install_paths():
            if self.cancelled:
                return
            yield from scan_game(game_dir, self.name, lambda: self.cancelled, pattern=_EPIC_REDIST_DIR_RE)

        if self.cancelled:
            return
        yield from self._scan_launcher_logs()
        yield from self._scan_webcache()

    def _scan_launcher_logs(self) -> Iterator[JunkEntry]:
        log_dirs = [data_dir / "Saved" / "Logs" for data_dir in self._launcher_data_dirs()]
        log_dirs.append(self._platform.home() / "Library" / "Logs" / "Unreal Engine" / "EpicGamesLauncher")
        yield from scan_launcher_logs(log_dirs, self.name, lambda: self.cancelled, "Epic Games Launcher log")

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
                        game_root=data_dir,
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
                    game_root=macos_cache,
                )
