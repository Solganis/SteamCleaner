from pathlib import Path

import pytest

from steamcleaner.platform.base import PlatformAdapter
from steamcleaner.scanner.exclusions import ExclusionRegistry


class FakePlatformAdapter(PlatformAdapter):
    def __init__(self, *, install_path: Path | None = None, home_dir: Path | None = None):
        self._install_path = install_path
        self._home = home_dir or Path.home()
        self._registry: dict[tuple[str, str, str], str] = {}
        if install_path:
            self._registry[("HKLM", r"SOFTWARE\Wow6432Node\Valve\Steam", "InstallPath")] = str(install_path)

    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        return self._registry.get((key, subkey, value_name))

    def appdata_local(self) -> Path:
        return self._home / ".local" / "share"

    def appdata_roaming(self) -> Path:
        return self._home / ".config"

    def home(self) -> Path:
        return self._home

    def program_files(self) -> list[Path]:
        return []


def build_fake_steam_tree(root: Path, games: dict[str, dict[str, list[str]]]) -> Path:
    """Build a fake Steam directory tree.

    Args:
        root: tmp_path root
        games: {game_name: {subdir_name: [filenames]}}

    Returns:
        Steam install path
    """
    steam = root / "Steam"
    common = steam / "steamapps" / "common"
    common.mkdir(parents=True)
    for game_name, subdirs in games.items():
        game_dir = common / game_name
        game_dir.mkdir()
        for subdir_name, files in subdirs.items():
            subdir = game_dir / subdir_name if subdir_name else game_dir
            subdir.mkdir(parents=True, exist_ok=True)
            for filename in files:
                file_path = subdir / filename
                file_path.write_bytes(b"\x00" * 1024)
    return steam


@pytest.fixture
def exclusion_registry() -> ExclusionRegistry:
    return ExclusionRegistry()


@pytest.fixture
def fake_platform(tmp_path: Path) -> FakePlatformAdapter:
    return FakePlatformAdapter(install_path=None)
