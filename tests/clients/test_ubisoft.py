from pathlib import Path

from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.clients.ubisoft import UbisoftClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry

_REGISTRY_LAUNCHER_PATH = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher"
_REGISTRY_INSTALLS_PATH = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"


def _make_ubisoft_env(
    tmp_path: Path,
    games: dict[str, dict[str, list[str]]] | None = None,
    launcher_exists: bool = True,
    registry_games: dict[str, Path] | None = None,
) -> tuple[FakePlatformAdapter, UbisoftClient]:
    home = tmp_path / "home"
    programdata = tmp_path / "ProgramData"
    program_files = tmp_path / "ProgramFiles"

    launcher_dir = program_files / "Ubisoft" / "Ubisoft Game Launcher"

    if launcher_exists:
        launcher_dir.mkdir(parents=True)

    if games:
        games_dir = launcher_dir / "games"
        games_dir.mkdir(parents=True, exist_ok=True)
        for game_name, subdirs in games.items():
            game_dir = games_dir / game_name
            game_dir.mkdir(parents=True, exist_ok=True)
            for subdir_name, files in subdirs.items():
                subdir = game_dir / subdir_name if subdir_name else game_dir
                subdir.mkdir(parents=True, exist_ok=True)
                for filename in files:
                    (subdir / filename).write_bytes(b"\x00" * 1024)

    platform = FakePlatformAdapter(
        home_dir=home,
        program_files_dirs=[program_files],
        programdata_dir=programdata,
    )

    if launcher_exists:
        platform.set_registry("HKLM", _REGISTRY_LAUNCHER_PATH, "InstallDir", str(launcher_dir))

    if registry_games:
        game_ids = []
        for game_id, install_path in registry_games.items():
            game_ids.append(game_id)
            platform.set_registry("HKLM", rf"{_REGISTRY_INSTALLS_PATH}\{game_id}", "InstallDir", str(install_path))
        platform.set_registry_subkeys("HKLM", _REGISTRY_INSTALLS_PATH, game_ids)

    return platform, UbisoftClient(platform, ExclusionRegistry())


class TestUbisoftDetection:
    def test_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()

    def test_installed_via_registry(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        assert_that(client.is_installed()).is_true()

    def test_installed_via_appdata(self, tmp_path: Path):
        home = tmp_path / "home"
        appdata = home / ".local" / "share" / "Ubisoft Game Launcher"
        appdata.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=home)
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.name).is_equal_to("Ubisoft Connect")


class TestUbisoftGameDiscovery:
    def test_discovers_from_default_games_dir(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"Assassin's Creed": {"": []}})
        paths = client.game_install_paths()
        assert_that(any(path.name == "Assassin's Creed" for path in paths)).is_true()

    def test_discovers_from_registry(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "FarCry6"
        game_dir.mkdir(parents=True)
        platform, client = _make_ubisoft_env(tmp_path, registry_games={"635": game_dir})
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)

    def test_registry_nonexistent_path_skipped(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, registry_games={"999": tmp_path / "nonexistent"})
        paths = client.game_install_paths()
        assert_that(paths).is_length(0)

    def test_no_duplicate_paths(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"": []}})
        game_path = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        platform.set_registry_subkeys("HKLM", _REGISTRY_INSTALLS_PATH, ["635"])
        platform.set_registry("HKLM", rf"{_REGISTRY_INSTALLS_PATH}\635", "InstallDir", str(game_path))
        paths = client.game_install_paths()
        assert_that(paths.count(game_path)).is_equal_to(1)

    def test_no_launcher_dir_still_uses_registry(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "FarCry6"
        game_dir.mkdir(parents=True)
        home = tmp_path / "home"
        platform = FakePlatformAdapter(home_dir=home, programdata_dir=tmp_path / "ProgramData")
        platform.set_registry_subkeys("HKLM", _REGISTRY_INSTALLS_PATH, ["635"])
        platform.set_registry("HKLM", rf"{_REGISTRY_INSTALLS_PATH}\635", "InstallDir", str(game_dir))
        client = UbisoftClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)


class TestUbisoftRedistScan:
    def test_finds_common_redist(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(
            tmp_path,
            games={"FarCry6": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(1)
        assert_that(redist[0].size_bytes).is_equal_to(2048)
        assert_that(redist[0].client_name).is_equal_to("Ubisoft Connect")

    def test_finds_support_dir(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(
            tmp_path,
            games={"FarCry6": {"support": ["dxsetup.exe"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(1)

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(
            tmp_path,
            games={"FarCry6": {"_CommonRedist": ["readme.txt"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(0)

    def test_exe_outside_redist_ignored(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"bin": ["game.exe"]}})
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist).is_length(0)


class TestUbisoftDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(1)

    def test_ignores_zero_size_dumps(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        (game_dir / "empty.dmp").write_bytes(b"")
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(0)


class TestUbisoftLogScan:
    def test_finds_large_game_logs(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)

    def test_finds_launcher_logs(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        logs_dir = launcher_dir / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "upc.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)
        assert_that(logs[0].description).is_equal_to("Ubisoft Connect launcher log")

    def test_finds_appdata_logs(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        logs_dir = tmp_path / "home" / ".local" / "share" / "Ubisoft Game Launcher" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "debug.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)

    def test_ignores_small_launcher_logs(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        logs_dir = launcher_dir / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)

    def test_ignores_small_appdata_logs(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        logs_dir = tmp_path / "home" / ".local" / "share" / "Ubisoft Game Launcher" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "tiny.log").write_bytes(b"\x00" * 500)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)


class TestUbisoftLauncherCache:
    def test_finds_cache(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        cache_dir = launcher_dir / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "assets.bin").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(1)
        assert_that(cache[0].description).is_equal_to("Ubisoft Connect cache")

    def test_ignores_empty_cache(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        cache_dir = launcher_dir / "cache"
        cache_dir.mkdir(parents=True)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert_that(cache).is_length(0)


class TestUbisoftLauncherCrashes:
    def test_finds_crashes(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        crashes_dir = launcher_dir / "crashes"
        crashes_dir.mkdir(parents=True)
        (crashes_dir / "dump.dmp").write_bytes(b"\x00" * 2048)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(1)
        assert_that(dumps[0].description).is_equal_to("Ubisoft Connect crash dumps")

    def test_ignores_empty_crashes(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path)
        launcher_dir = tmp_path / "ProgramFiles" / "Ubisoft" / "Ubisoft Game Launcher"
        crashes_dir = launcher_dir / "crashes"
        crashes_dir.mkdir(parents=True)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(0)


class TestUbisoftUnicode:
    def test_cyrillic_game_name(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"Игра Тест": {"_CommonRedist": ["vcredist.exe"]}})
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)

    def test_cjk_game_name(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"ゲームテスト": {"redist": ["setup.msi"]}})
        entries = list(client.scan_junk())
        assert_that(entries).is_length(1)


class TestUbisoftEdgeCases:
    def test_not_installed_yields_nothing(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = UbisoftClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert_that(entries).is_equal_to([])

    def test_empty_game_dir(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"EmptyGame": {"": []}})
        entries = list(client.scan_junk())
        assert_that(entries).is_equal_to([])

    def test_exclusion_filters(self, tmp_path: Path):
        platform, client = _make_ubisoft_env(tmp_path, games={"FarCry6": {"_CommonRedist": ["vcredist.exe"]}})
        exclusions = ExclusionRegistry()
        exclusions.add("FarCry6", "test exclusion")
        client_with_excl = UbisoftClient(platform, exclusions)
        safe_entries = list(client_with_excl.scan_safe())
        assert_that(safe_entries).is_length(0)


class TestUbisoftWinePrefix:
    def test_installed_via_wine_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        (prefix / "Program Files (x86)" / "Ubisoft" / "Ubisoft Game Launcher").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_installed_via_wine_prefix_program_files(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        (prefix / "Program Files" / "Ubisoft" / "Ubisoft Game Launcher").mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_true()

    def test_not_installed_empty_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        prefix.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        assert_that(client.is_installed()).is_false()

    def test_discovers_games_from_wine_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files (x86)" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)

    def test_discovers_games_from_program_files_prefix(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths).contains(game_dir)

    def test_scans_junk_in_wine_prefix_game(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files (x86)" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        redist = game_dir / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "vcredist.exe").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        client = UbisoftClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(1)

    def test_no_duplicate_with_registry(self, tmp_path: Path):
        prefix = tmp_path / "wine" / "drive_c"
        game_dir = prefix / "Program Files (x86)" / "Ubisoft" / "Ubisoft Game Launcher" / "games" / "FarCry6"
        game_dir.mkdir(parents=True)
        platform = FakePlatformAdapter(home_dir=tmp_path / "home", wine_prefix_dirs=[prefix])
        platform.set_registry_subkeys("HKLM", _REGISTRY_INSTALLS_PATH, ["635"])
        platform.set_registry("HKLM", rf"{_REGISTRY_INSTALLS_PATH}\635", "InstallDir", str(game_dir))
        client = UbisoftClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert_that(paths.count(game_dir)).is_equal_to(1)
