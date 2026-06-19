import json
from pathlib import Path
from unittest.mock import patch

from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.clients.epic import EpicClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry


def _make_epic_env(
    tmp_path: Path,
    games: dict[str, dict[str, list[str]]] | None = None,
    manifest_locations: list[Path] | None = None,
    launcher_exists: bool = True,
) -> tuple[FakePlatformAdapter, EpicClient]:
    home = tmp_path / "home"
    appdata_local = home / ".local" / "share"

    if launcher_exists:
        (appdata_local / "EpicGamesLauncher").mkdir(parents=True)

    program_files = tmp_path / "ProgramFiles"
    epic_games = program_files / "Epic Games"
    programdata = tmp_path / "ProgramData"

    if games:
        for game_name, subdirs in games.items():
            game_dir = epic_games / game_name
            game_dir.mkdir(parents=True, exist_ok=True)
            for subdir_name, files in subdirs.items():
                subdir = game_dir / subdir_name if subdir_name else game_dir
                subdir.mkdir(parents=True, exist_ok=True)
                for filename in files:
                    (subdir / filename).write_bytes(b"\x00" * 1024)

    if manifest_locations:
        manifests_dir = programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests_dir.mkdir(parents=True)
        for index, location in enumerate(manifest_locations):
            manifest = {"InstallLocation": str(location)}
            (manifests_dir / f"game_{index}.item").write_text(json.dumps(manifest), encoding="utf-8")

    platform = FakePlatformAdapter(
        home_dir=home,
        program_files_dirs=[program_files],
        programdata_dir=programdata,
    )
    return platform, EpicClient(platform, ExclusionRegistry())


class TestEpicClientDetection:
    def test_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()

    def test_installed(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        assert_that(client.is_installed()).is_true()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.name).is_equal_to("Epic Games")


class TestEpicGameDiscovery:
    def test_discovers_from_program_files(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        paths = client.game_install_paths()
        assert_that(any(path.name == "Fortnite" for path in paths)).is_true()

    def test_skips_launcher_dir(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Launcher": {"": []}, "Fortnite": {"": []}})
        paths = client.game_install_paths()
        names = [path.name for path in paths]
        assert_that(names).does_not_contain("Launcher")
        assert_that(names).contains("Fortnite")

    def test_discovers_from_manifests(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "MyGame"
        game_dir.mkdir(parents=True)
        _platform, client = _make_epic_env(tmp_path, manifest_locations=[game_dir])
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)

    def test_manifest_nonexistent_path_skipped(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, manifest_locations=[tmp_path / "nonexistent" / "game"])
        paths = client.game_install_paths()
        assert_that(paths).is_length(0)

    def test_manifest_invalid_json_skipped(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        programdata = tmp_path / "ProgramData"
        manifests = programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        (manifests / "broken.item").write_text("{invalid json", encoding="utf-8")
        paths = client.game_install_paths()
        assert_that(paths).is_length(0)

    def test_no_duplicate_paths(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_path = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        programdata = tmp_path / "ProgramData"
        manifests = programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        manifest = {"InstallLocation": str(game_path)}
        (manifests / "fortnite.item").write_text(json.dumps(manifest), encoding="utf-8")
        paths = client.game_install_paths()
        assert_that(paths.count(game_path)).is_equal_to(1)

    def test_manifest_non_item_file_skipped(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        manifests = tmp_path / "ProgramData" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        (manifests / "notes.txt").write_text("not a manifest", encoding="utf-8")
        assert_that(client.game_install_paths()).is_length(0)

    def test_manifest_empty_install_location_skipped(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        manifests = tmp_path / "ProgramData" / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        (manifests / "g.item").write_text(json.dumps({"InstallLocation": ""}), encoding="utf-8")
        assert_that(client.game_install_paths()).is_length(0)

    def test_shared_programdata_no_duplicate(self, tmp_path: Path):
        home = tmp_path / "home"
        programdata = tmp_path / "ProgramData"
        game_dir = programdata / "Epic Games" / "Fortnite"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=home, program_files_dirs=[programdata], programdata_dir=programdata)
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.game_install_paths().count(game_dir)).is_equal_to(1)


class TestEpicRedistScan:
    def test_finds_redist(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(1)
        assert_that(redist[0].size_bytes).is_equal_to(2048)
        assert_that(redist[0].client_name).is_equal_to("Epic Games")

    def test_finds_prerequisites(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"Prerequisites": ["EpicPrereqSetup.exe"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(1)

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["readme.txt", "notes.pdf"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(0)

    def test_nested_redist_no_duplicates(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={
                "Fortnite": {
                    "__Installer": ["setup.exe"],
                    "__Installer/directx/redist": ["dxsetup.exe"],
                },
            },
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(1)
        assert_that(str(redist[0].path)).contains("__Installer")


class TestEpicDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        (game_dir / "mini.mdmp").write_bytes(b"\x00" * 256)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(2)

    def test_ignores_zero_size_dumps(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "empty.dmp").write_bytes(b"")
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(0)


class TestEpicLogScan:
    def test_finds_large_game_logs(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)

    def test_ignores_small_game_logs(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)

    def test_finds_launcher_logs(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        logs_dir = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EpicGamesLauncher.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)
        assert_that(logs[0].description).is_equal_to("Epic Games Launcher log")

    def test_ignores_small_launcher_logs(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        logs_dir = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)


class TestEpicWebcache:
    def test_finds_webcache(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache"
        webcache.mkdir(parents=True)
        (webcache / "cache_data.bin").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(1)
        assert_that(cache[0].size_bytes).is_equal_to(4096)

    def test_finds_webcache_with_port_suffix(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache_4430"
        webcache.mkdir(parents=True)
        (webcache / "data.bin").write_bytes(b"\x00" * 2048)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(1)
        assert_that(str(cache[0].path)).contains("webcache_4430")

    def test_finds_multiple_webcache_dirs(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        saved = home / ".local" / "share" / "EpicGamesLauncher" / "Saved"
        for name in ("webcache", "webcache_4430", "webcache_8888"):
            cache_dir = saved / name
            cache_dir.mkdir(parents=True)
            (cache_dir / "data.bin").write_bytes(b"\x00" * 1024)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(3)

    def test_deduplicates_webcache_across_data_dirs(self, tmp_path: Path):
        home = tmp_path / "home"
        data_dir = home / ".local" / "share" / "EpicGamesLauncher"
        saved = data_dir / "Saved"
        webcache = saved / "webcache"
        webcache.mkdir(parents=True)
        (webcache / "data.bin").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(
            home_dir=home, program_files_dirs=[tmp_path / "PF"], programdata_dir=tmp_path / "PD"
        )
        client = EpicClient(platform, ExclusionRegistry())
        with patch.object(client, "_launcher_data_dirs", return_value=[data_dir, data_dir]):
            entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(1)

    def test_ignores_empty_webcache(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache"
        webcache.mkdir(parents=True)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(0)

    def test_ignores_empty_macos_cache(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path)
        macos_cache = tmp_path / "home" / "Library" / "Caches" / "com.epicgames.EpicGamesLauncher"
        macos_cache.mkdir(parents=True)
        cache = [entry for entry in client.scan_junk() if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(0)


class TestEpicUnicode:
    def test_cyrillic_game_name(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={"Игра Тест": {"_CommonRedist": ["vcredist.exe"]}},
        )
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)

    def test_cjk_game_name(self, tmp_path: Path):
        _platform, client = _make_epic_env(
            tmp_path,
            games={"ゲームテスト": {"redist": ["setup.msi"]}},
        )
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)


class TestEpicEdgeCases:
    def test_not_installed_yields_nothing(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_equal_to([])

    def test_empty_game_dir(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"EmptyGame": {"": []}})
        entries = list(client.scan_junk())
        assert_that(entries).is_equal_to([])

    def test_exe_outside_redist_ignored(self, tmp_path: Path):
        _platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"Binaries": ["game.exe"]}})
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(0)

    def test_exclusion_filters(self, tmp_path: Path):
        platform, _client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["vcredist.exe"]}},
        )
        exclusions = ExclusionRegistry()
        exclusions.add("Fortnite", "test exclusion")
        client_with_excl = EpicClient(platform, exclusions)
        safe_entries = list(client_with_excl.scan_safe())
        assert_that(safe_entries).is_length(0)


class TestEpicWinePrefix:
    def test_installed_via_wine_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        (prefix / "Program Files" / "Epic Games" / "Fortnite").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_not_installed_without_epic_dir(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        prefix.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()

    def test_game_paths_wine_prefix_without_epic_dir(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        prefix.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        assert_that(client.game_install_paths()).is_length(0)

    def test_discovers_games_from_wine_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files" / "Epic Games" / "Fortnite"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)

    def test_skips_launcher_dir_in_wine_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        epic_dir = prefix / "Program Files" / "Epic Games"
        (epic_dir / "Launcher").mkdir(parents=True)
        (epic_dir / "Fortnite").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        names = [path.name for path in paths]
        assert_that(names).does_not_contain("Launcher")
        assert_that(names).contains("Fortnite")

    def test_scans_junk_in_wine_prefix_game(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files" / "Epic Games" / "Fortnite"
        redist = game_dir / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "vcredist.exe").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(1)

    def test_no_duplicate_with_program_files(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files" / "Epic Games" / "Fortnite"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(
            home_dir=tmp_path / "home",
            program_files_dirs=[prefix / "Program Files"],
            wine_prefix_dirs=[prefix],
        )
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths.count(game_dir)).is_equal_to(1)

    def test_multiple_wine_prefixes(self, tmp_path: Path):
        prefix1 = tmp_path / "wine1" / "drive_c"
        prefix2 = tmp_path / "wine2" / "drive_c"
        game1 = prefix1 / "Program Files" / "Epic Games" / "Fortnite"
        game2 = prefix2 / "Program Files" / "Epic Games" / "RocketLeague"
        game1.mkdir(parents=True)
        game2.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix1, prefix2])
        client = EpicClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths).contains(game1)
        assert_that(paths).contains(game2)
