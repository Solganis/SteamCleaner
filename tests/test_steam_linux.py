from __future__ import annotations

from pathlib import Path

from steamcleaner.clients.steam import SteamClient
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter


class TestSteamLinuxDetection:
    def test_finds_steam_via_dot_steam(self, tmp_path: Path):
        steam_dir = tmp_path / ".steam" / "steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_finds_steam_via_xdg_data(self, tmp_path: Path):
        steam_dir = tmp_path / ".local" / "share" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_finds_steam_via_flatpak(self, tmp_path: Path):
        steam_dir = tmp_path / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_not_installed_no_paths(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert not client.is_installed()


class TestSteamLinuxScan:
    def _make_steam(self, tmp_path: Path) -> tuple[FakePlatformAdapter, Path]:
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
        assert len(entries) == 1
        assert entries[0].category.value == "redistributable"

    def test_finds_shader_cache_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        cache = steam_dir / "steamapps" / "shadercache" / "12345"
        cache.mkdir(parents=True)
        (cache / "data.bin").write_bytes(b"\x00" * 4096)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [e for e in entries if e.category.value == "shader_cache"]
        assert len(shader_entries) == 1

    def test_finds_dumps_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        dumps = steam_dir / "dumps"
        dumps.mkdir()
        (dumps / "crash.dmp").write_bytes(b"\x00" * 512)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [e for e in entries if e.category.value == "crash_dump"]
        assert len(dump_entries) == 1

    def test_finds_logs_on_linux(self, tmp_path: Path):
        platform, steam_dir = self._make_steam(tmp_path)
        logs = steam_dir / "logs"
        logs.mkdir()
        (logs / "steam.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [e for e in entries if e.category.value == "old_log"]
        assert len(log_entries) == 1
