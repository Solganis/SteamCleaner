"""Tests for macOS-specific paths across all game clients."""

import json
from pathlib import Path

from conftest import FakePlatformAdapter

from steamcleaner.clients.ea_app import EaAppClient
from steamcleaner.clients.epic import EpicClient
from steamcleaner.clients.gog import GogClient
from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry


def _macos_platform(tmp_path: Path, **kwargs) -> FakePlatformAdapter:
    return FakePlatformAdapter(
        home_dir=tmp_path,
        appdata_local_dir=tmp_path / "Library" / "Application Support",
        programdata_dir=tmp_path / "Shared",
        **kwargs,
    )


class TestMacOSPlatformAdapter:
    def test_appdata_local(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        assert platform.appdata_local() == tmp_path / "Library" / "Application Support"

    def test_programdata(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        assert platform.programdata() == tmp_path / "Shared"

    def test_home(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        assert platform.home() == tmp_path


class TestSteamMacOS:
    def test_finds_steam_via_application_support(self, tmp_path: Path):
        steam_dir = tmp_path / "Library" / "Application Support" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_not_installed_no_steam_dir(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_scans_redist_on_macos(self, tmp_path: Path):
        steam_dir = tmp_path / "Library" / "Application Support" / "Steam"
        game = steam_dir / "steamapps" / "common" / "TestGame"
        redist = game / "_CommonRedist" / "DirectX"
        redist.mkdir(parents=True)
        (redist / "DXSETUP.exe").write_bytes(b"\x00" * 2048)
        platform = _macos_platform(tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert len(entries) == 1
        assert entries[0].category == JunkCategory.REDISTRIBUTABLE

    def test_scans_shader_cache_on_macos(self, tmp_path: Path):
        steam_dir = tmp_path / "Library" / "Application Support" / "Steam"
        cache = steam_dir / "steamapps" / "shadercache" / "12345"
        cache.mkdir(parents=True)
        (cache / "data.bin").write_bytes(b"\x00" * 4096)
        platform = _macos_platform(tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(shader_entries) == 1

    def test_scans_dumps_on_macos(self, tmp_path: Path):
        steam_dir = tmp_path / "Library" / "Application Support" / "Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        dumps = steam_dir / "dumps"
        dumps.mkdir()
        (dumps / "crash.dmp").write_bytes(b"\x00" * 512)
        platform = _macos_platform(tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dump_entries) == 1


class TestEpicMacOS:
    def test_installed_via_application_support(self, tmp_path: Path):
        launcher_dir = tmp_path / "Library" / "Application Support" / "Epic" / "EpicGamesLauncher"
        launcher_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_not_installed(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_discovers_games_from_manifests(self, tmp_path: Path):
        manifests = tmp_path / "Library" / "Application Support" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        game_dir = tmp_path / "Games" / "Fortnite"
        game_dir.mkdir(parents=True)
        manifest = manifests / "game.item"
        manifest.write_text(json.dumps({"InstallLocation": str(game_dir)}), encoding="utf-8")
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert game_dir in paths

    def test_discovers_games_from_shared(self, tmp_path: Path):
        shared_epic = tmp_path / "Shared" / "Epic Games"
        game_dir = shared_epic / "Fortnite"
        game_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert game_dir in paths

    def test_shared_skips_launcher_dir(self, tmp_path: Path):
        shared_epic = tmp_path / "Shared" / "Epic Games"
        (shared_epic / "Launcher").mkdir(parents=True)
        game_dir = shared_epic / "RealGame"
        game_dir.mkdir()
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert game_dir in paths
        assert not any(path.name == "Launcher" for path in paths)

    def test_scans_macos_logs(self, tmp_path: Path):
        logs_dir = tmp_path / "Library" / "Logs" / "Unreal Engine" / "EpicGamesLauncher"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EpicGamesLauncher.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(log_entries) == 1

    def test_scans_macos_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "com.epicgames.EpicGamesLauncher"
        cache_dir.mkdir(parents=True)
        (cache_dir / "data.bin").write_bytes(b"\x00" * 4096)
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_game_redist(self, tmp_path: Path):
        shared_epic = tmp_path / "Shared" / "Epic Games"
        game = shared_epic / "TestGame"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "setup.exe").write_bytes(b"\x00" * 2048)
        platform = _macos_platform(tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist_entries) == 1


class TestEaAppMacOS:
    def test_installed_via_ea_desktop(self, tmp_path: Path):
        ea_dir = tmp_path / "Library" / "Application Support" / "Electronic Arts" / "EA Desktop"
        ea_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_installed_via_ea_app(self, tmp_path: Path):
        ea_dir = tmp_path / "Library" / "Application Support" / "Electronic Arts" / "EA app"
        ea_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_installed_via_origin(self, tmp_path: Path):
        origin_dir = tmp_path / "Library" / "Application Support" / "Origin"
        origin_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_not_installed(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_discovers_games_from_applications(self, tmp_path: Path):
        apps = tmp_path / "Applications"
        game_dir = apps / "EA Games" / "The Sims 4"
        game_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path, program_files_dirs=[apps])
        client = EaAppClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert game_dir in paths

    def test_scans_macos_origin_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "com.ea.Origin"
        cache_dir.mkdir(parents=True)
        (cache_dir / "data.bin").write_bytes(b"\x00" * 4096)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_macos_ea_app_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "EA app"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cache.bin").write_bytes(b"\x00" * 2048)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_macos_migrator_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "com.EA.EA-app-Migrator"
        cache_dir.mkdir(parents=True)
        (cache_dir / "migrator.bin").write_bytes(b"\x00" * 4096)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_macos_origin_library_cache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "Origin"
        cache_dir.mkdir(parents=True)
        (cache_dir / "origin.bin").write_bytes(b"\x00" * 2048)
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_ea_app_logs(self, tmp_path: Path):
        logs_dir = tmp_path / "Library" / "Application Support" / "Electronic Arts" / "EA app" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EAApp.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = _macos_platform(tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(log_entries) == 1


class TestGogMacOS:
    def test_installed_via_shared_data(self, tmp_path: Path):
        galaxy_dir = tmp_path / "Shared" / "GOG.com" / "Galaxy"
        galaxy_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_installed_via_gog_games_dir(self, tmp_path: Path):
        gog_games = tmp_path / "GOG Games"
        gog_games.mkdir()
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_installed_via_application_support(self, tmp_path: Path):
        galaxy_dir = tmp_path / "Library" / "Application Support" / "GOG.com" / "Galaxy"
        galaxy_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert client.is_installed()

    def test_not_installed(self, tmp_path: Path):
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_discovers_games_from_gog_games(self, tmp_path: Path):
        gog_games = tmp_path / "GOG Games"
        game_dir = gog_games / "Baldurs Gate"
        game_dir.mkdir(parents=True)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert game_dir in paths

    def test_scans_launcher_logs(self, tmp_path: Path):
        galaxy_dir = tmp_path / "Shared" / "GOG.com" / "Galaxy"
        logs_dir = galaxy_dir / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "GalaxyClient.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(log_entries) == 1

    def test_scans_macos_webcache(self, tmp_path: Path):
        cache_dir = tmp_path / "Library" / "Caches" / "com.gog.galaxy"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cache.bin").write_bytes(b"\x00" * 4096)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        cache_entries = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache_entries) == 1

    def test_scans_crashdumps(self, tmp_path: Path):
        galaxy_dir = tmp_path / "Shared" / "GOG.com" / "Galaxy"
        crashes = galaxy_dir / "crashdumps"
        crashes.mkdir(parents=True)
        (crashes / "crash.dmp").write_bytes(b"\x00" * 512)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dump_entries) == 1

    def test_scans_macos_library_logs(self, tmp_path: Path):
        logs_dir = tmp_path / "Library" / "Logs" / "GOG.com" / "Galaxy"
        logs_dir.mkdir(parents=True)
        (logs_dir / "GalaxyClient.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(log_entries) == 1

    def test_scans_game_redist(self, tmp_path: Path):
        gog_games = tmp_path / "GOG Games"
        game = gog_games / "Witcher 3"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "vcredist.exe").write_bytes(b"\x00" * 2048)
        platform = _macos_platform(tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist_entries) == 1
