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


def _parse_library_folders_vdf(path: Path) -> list[Path]:
    """Parse libraryfolders.vdf to extract library paths."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    paths: list[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        p = Path(match.group(1).replace("\\\\", "\\"))
        if p.is_dir():
            paths.append(p)
    return paths


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                with contextlib.suppress(OSError):
                    total += f.stat().st_size
    except OSError:
        pass
    return total


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
            val = self._platform.read_registry_str("HKLM", subkey, "InstallPath")
            if val:
                p = Path(val)
                if p.is_dir():
                    self._install_path = p
                    return p
        return None

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
            common = library / "steamapps" / "common"
            if not common.is_dir():
                continue
            try:
                game_dirs = list(common.iterdir())
            except OSError:
                continue
            for game_dir in game_dirs:
                if not game_dir.is_dir():
                    continue
                yield from self._scan_game_dir(game_dir)

    def _scan_game_dir(self, game_dir: Path) -> Iterator[JunkEntry]:
        try:
            subdirs = list(game_dir.iterdir())
        except OSError:
            return
        for subdir in subdirs:
            if not subdir.is_dir():
                continue
            if _REDIST_DIR_RE.search(subdir.name):
                junk_files = [
                    f for f in subdir.rglob("*")
                    if f.is_file() and f.suffix.lower() in _JUNK_EXTENSIONS
                ]
                if junk_files:
                    size = sum(f.stat().st_size for f in junk_files)
                    yield JunkEntry(
                        path=subdir,
                        category=JunkCategory.REDISTRIBUTABLE,
                        size_bytes=size,
                        client_name=self.name,
                        description=f"Redistributable in {game_dir.name}/{subdir.name}",
                    )
