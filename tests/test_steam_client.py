from __future__ import annotations

from pathlib import Path

from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter, build_fake_steam_tree


class TestSteamClientDetection:
    def test_not_installed(self):
        platform = FakePlatformAdapter(install_path=None)
        client = SteamClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_installed(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        steam.mkdir()
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(install_path=None)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.name == "Steam"


class TestSteamRedistScan:
    def test_finds_redist_dir(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]},
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert len(entries) == 1
        assert entries[0].category == JunkCategory.REDISTRIBUTABLE
        assert entries[0].size_bytes == 2048

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {"_CommonRedist": ["readme.txt", "notes.pdf"]},
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert len(entries) == 0

    def test_nested_redist_no_duplicates(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {
                "__Installer": ["setup.exe"],
                "__Installer/directx/redist": ["dxsetup.exe"],
            },
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = [e for e in client.scan_junk() if e.category == JunkCategory.REDISTRIBUTABLE]
        assert len(entries) == 1
        assert "__Installer" in str(entries[0].path)

    def test_exclusion_filters(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "Steamworks Shared": {"redist": ["vcredist.exe"]},
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        safe_entries = list(client.scan_safe())
        assert len(safe_entries) == 0

    def test_unicode_game_name(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "Игра Тест": {"_CommonRedist": ["vcredist.exe"]},
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert len(entries) == 1

    def test_cjk_game_name(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "ゲームテスト": {"redist": ["setup.msi"]},
        })
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert len(entries) == 1


class TestSteamDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {"": []},
        })
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        (game_dir / "mini.mdmp").write_bytes(b"\x00" * 256)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        dumps = [e for e in client.scan_junk() if e.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 2


class TestSteamLogScan:
    def test_finds_large_logs(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {"": []},
        })
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        logs = [e for e in client.scan_junk() if e.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1

    def test_ignores_small_logs(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {
            "TestGame": {"": []},
        })
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "small.log").write_bytes(b"\x00" * 100)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        logs = [e for e in client.scan_junk() if e.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0


class TestSteamShaderCache:
    def test_finds_shader_cache(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        cache_dir = steam / "steamapps" / "shadercache" / "12345"
        cache_dir.mkdir(parents=True)
        (cache_dir / "shader.bin").write_bytes(b"\x00" * 4096)
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        shaders = [e for e in client.scan_junk() if e.category == JunkCategory.SHADER_CACHE]
        assert len(shaders) == 1
        assert shaders[0].size_bytes == 4096


class TestSteamClientLogs:
    def test_finds_steam_logs(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        logs = steam / "logs"
        logs.mkdir(parents=True)
        (logs / "bootstrap.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        log_entries = [e for e in client.scan_junk() if e.category == JunkCategory.OLD_LOG]
        assert len(log_entries) == 1
        assert log_entries[0].description == "Steam client logs"

    def test_finds_steam_dumps(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        dumps = steam / "dumps"
        dumps.mkdir(parents=True)
        (dumps / "crash.dmp").write_bytes(b"\x00" * 2048)
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        dump_entries = [e for e in client.scan_junk() if e.category == JunkCategory.CRASH_DUMP]
        assert len(dump_entries) == 1
        assert dump_entries[0].description == "Steam client crash dumps"
