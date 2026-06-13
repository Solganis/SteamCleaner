from pathlib import Path

from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.clients.steam import SteamClient
from steamcleaner.scanner.exclusions import ExclusionRegistry


class TestSteamLinuxDetection:
    def test_finds_steam_via_dot_steam(self, tmp_path: Path):
        steam_dir = tmp_path / ".steam" / "steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_finds_steam_via_xdg_data(self, tmp_path: Path):
        steam_dir = tmp_path / ".local" / "share" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_finds_steam_via_flatpak(self, tmp_path: Path):
        steam_dir = tmp_path / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_not_installed_no_paths(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()


class TestSteamLinuxScan:
    @staticmethod
    def _make_steam(tmp_path: Path) -> tuple[FakePlatformAdapter, Path]:
        steam_dir = tmp_path / ".local" / "share" / "Steam"
        common = steam_dir / "steamapps" / "common"
        common.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        return platform, steam_dir

    def test_finds_redist_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        game = steam_dir / "steamapps" / "common" / "TestGame"
        redist = game / "_CommonRedist" / "vcredist"
        redist.mkdir(parents=True)
        (redist / "vc_redist.exe").write_bytes(b"\x00" * 2048)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)
        assert_that(entries[0].category.value).is_equal_to("redistributable")

    def test_finds_shader_cache_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        cache = steam_dir / "steamapps" / "shadercache" / "12345"
        cache.mkdir(parents=True)
        (cache / "data.bin").write_bytes(b"\x00" * 4096)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [entry for entry in entries if entry.category.value == "shader_cache"]
        assert_that(shader_entries).is_length(1)

    def test_finds_dumps_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        dumps = steam_dir / "dumps"
        dumps.mkdir()
        (dumps / "crash.dmp").write_bytes(b"\x00" * 512)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category.value == "crash_dump"]
        assert_that(dump_entries).is_length(1)
