from pathlib import Path

from assertpy2 import assert_that
from helpers import FakePlatformAdapter, build_fake_steam_tree

from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry


class TestSteamClientDetection:
    def test_not_installed(self):
        platform = FakePlatformAdapter(install_path=None)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()

    def test_installed(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        steam.mkdir()
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(install_path=None)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.name).is_equal_to("Steam")


class TestSteamRedistScan:
    def test_finds_redist_dir(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]},
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)
        assert_that(entries[0].category).is_equal_to(JunkCategory.REDISTRIBUTABLE)
        assert_that(entries[0].size_bytes).is_equal_to(2048)

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {"_CommonRedist": ["readme.txt", "notes.pdf"]},
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_length(0)

    def test_nested_redist_no_duplicates(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {
                    "__Installer": ["setup.exe"],
                    "__Installer/directx/redist": ["dxsetup.exe"],
                },
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = [entry for entry in client.scan_junk() if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(entries).is_length(1)
        assert_that(str(entries[0].path)).contains("__Installer")

    def test_exclusion_filters(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "Steamworks Shared": {"redist": ["vcredist.exe"]},
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        safe_entries = list(client.scan_safe())
        assert_that(safe_entries).is_length(0)

    def test_unicode_game_name(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "Игра Тест": {"_CommonRedist": ["vcredist.exe"]},
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)

    def test_cjk_game_name(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "ゲームテスト": {"redist": ["setup.msi"]},
            },
        )
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)


class TestSteamDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {"": []},
            },
        )
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        (game_dir / "mini.mdmp").write_bytes(b"\x00" * 256)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        dumps = [e for e in client.scan_junk() if e.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(2)


class TestSteamLogScan:
    def test_finds_large_logs(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {"": []},
            },
        )
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        logs = [e for e in client.scan_junk() if e.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)

    def test_ignores_small_logs(self, tmp_path: Path):
        steam = build_fake_steam_tree(
            tmp_path,
            {
                "TestGame": {"": []},
            },
        )
        game_dir = steam / "steamapps" / "common" / "TestGame"
        (game_dir / "small.log").write_bytes(b"\x00" * 100)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        logs = [e for e in client.scan_junk() if e.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)


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
        assert_that(shaders).is_length(1)
        assert_that(shaders[0].size_bytes).is_equal_to(4096)


class TestSteamGameInstallPaths:
    def test_returns_game_dirs_from_library(self, tmp_path: Path):
        steam = build_fake_steam_tree(tmp_path, {"GameA": {"": []}, "GameB": {"": []}})
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        names = {path.name for path in paths}
        assert_that(names).is_equal_to({"GameA", "GameB"})

    def test_skips_library_without_common(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.game_install_paths()).is_equal_to([])


# noinspection PyUnresolvedReferences
class TestSteamAppidMap:
    def test_parses_manifest_files(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        steamapps = steam / "steamapps"
        (steamapps / "common").mkdir(parents=True)
        manifest = steamapps / "appmanifest_440.acf"
        manifest.write_text('"AppState"\n{\n\t"appid"\t\t"440"\n\t"name"\t\t"Team Fortress 2"\n}')
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        appid_map = client._build_appid_map(steam)
        assert_that(appid_map).is_equal_to({"440": "Team Fortress 2"})

    def test_skips_malformed_manifest(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        steamapps = steam / "steamapps"
        (steamapps / "common").mkdir(parents=True)
        (steamapps / "appmanifest_999.acf").write_text("garbage content no appid here")
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        appid_map = client._build_appid_map(steam)
        assert_that(appid_map).is_equal_to({})

    def test_multiple_manifests(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        steamapps = steam / "steamapps"
        (steamapps / "common").mkdir(parents=True)
        (steamapps / "appmanifest_440.acf").write_text('"AppState"\n{\n\t"appid"\t\t"440"\n\t"name"\t\t"TF2"\n}')
        (steamapps / "appmanifest_730.acf").write_text('"AppState"\n{\n\t"appid"\t\t"730"\n\t"name"\t\t"CS2"\n}')
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        appid_map = client._build_appid_map(steam)
        assert_that(appid_map).is_equal_to({"440": "TF2", "730": "CS2"})


class TestSteamClientLogs:
    def test_finds_steam_dumps(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        dumps = steam / "dumps"
        dumps.mkdir(parents=True)
        (dumps / "crash.dmp").write_bytes(b"\x00" * 2048)
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        dump_entries = [e for e in client.scan_junk() if e.category == JunkCategory.CRASH_DUMP]
        assert_that(dump_entries).is_length(1)
        assert_that(dump_entries[0].description).is_equal_to("Steam client crash dumps")
