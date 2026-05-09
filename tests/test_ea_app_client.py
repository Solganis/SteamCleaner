from pathlib import Path

from steamcleaner.clients.ea_app import EaAppClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter

_REGISTRY_GAMES_PATH = r"SOFTWARE\WOW6432Node\Origin Games"


def _make_ea_env(
    tmp_path: Path,
    games: dict[str, dict[str, list[str]]] | None = None,
    game_dir_name: str = "EA Games",
    ea_desktop_exists: bool = True,
    origin_exists: bool = False,
    registry_games: dict[str, Path] | None = None,
) -> tuple[FakePlatformAdapter, EaAppClient]:
    home = tmp_path / "home"
    appdata_local = home / ".local" / "share"

    if ea_desktop_exists:
        (appdata_local / "Electronic Arts" / "EA Desktop").mkdir(parents=True)

    if origin_exists:
        (appdata_local / "Origin").mkdir(parents=True)

    program_files = tmp_path / "ProgramFiles"
    programdata = tmp_path / "ProgramData"

    if games:
        for game_name, subdirs in games.items():
            game_dir = program_files / game_dir_name / game_name
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

    if registry_games:
        content_ids = []
        for content_id, install_path in registry_games.items():
            content_ids.append(content_id)
            platform.set_registry("HKLM", rf"{_REGISTRY_GAMES_PATH}\{content_id}", "Install Dir", str(install_path))
        platform.set_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH, content_ids)

    return platform, EaAppClient(platform, ExclusionRegistry())


class TestEaAppDetection:
    def test_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_installed_ea_desktop(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        assert client.is_installed()

    def test_installed_origin_legacy(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, ea_desktop_exists=False, origin_exists=True)
        assert client.is_installed()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        assert client.name == "EA App"


class TestEaGameDiscovery:
    def test_discovers_from_ea_games_dir(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"Battlefield 2042": {"": []}})
        paths = client._game_install_paths()
        assert any(path.name == "Battlefield 2042" for path in paths)

    def test_discovers_from_origin_games_dir(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"Mass Effect": {"": []}}, game_dir_name="Origin Games")
        paths = client._game_install_paths()
        assert any(path.name == "Mass Effect" for path in paths)

    def test_discovers_from_registry(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "FIFA"
        game_dir.mkdir(parents=True)
        platform, client = _make_ea_env(tmp_path, registry_games={"OFB-EAST:109552639": game_dir})
        paths = client._game_install_paths()
        assert game_dir in paths

    def test_registry_nonexistent_path_skipped(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, registry_games={"OFB-EAST:12345": tmp_path / "nonexistent"})
        paths = client._game_install_paths()
        assert len(paths) == 0

    def test_no_duplicate_paths(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"Battlefield 2042": {"": []}})
        game_path = tmp_path / "ProgramFiles" / "EA Games" / "Battlefield 2042"
        platform.set_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH, ["bf2042"])
        platform.set_registry("HKLM", rf"{_REGISTRY_GAMES_PATH}\bf2042", "Install Dir", str(game_path))
        paths = client._game_install_paths()
        assert paths.count(game_path) == 1


class TestEaRedistScan:
    def test_finds_common_redist(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"Battlefield 2042": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1
        assert redist[0].size_bytes == 2048
        assert redist[0].client_name == "EA App"

    def test_finds_installer_dir(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"NFS Heat": {"__Installer": ["installerdata.xml", "setup.exe"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1
        assert "__Installer" in str(redist[0].path)

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"NFS Heat": {"__Installer": ["installerdata.xml", "readme.txt"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0

    def test_nested_redist_no_duplicates(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={
                "Battlefield 2042": {
                    "__Installer": ["setup.exe"],
                    "__Installer/directx/redist": ["dxsetup.exe"],
                },
            },
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1
        assert "__Installer" in str(redist[0].path)


class TestEaDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"NFS Heat": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "EA Games" / "NFS Heat"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        (game_dir / "mini.mdmp").write_bytes(b"\x00" * 256)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 2

    def test_ignores_zero_size_dumps(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"NFS Heat": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "EA Games" / "NFS Heat"
        (game_dir / "empty.dmp").write_bytes(b"")
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 0


class TestEaLogScan:
    def test_finds_large_game_logs(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"NFS Heat": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "EA Games" / "NFS Heat"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1

    def test_ignores_small_game_logs(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"NFS Heat": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "EA Games" / "NFS Heat"
        (game_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0

    def test_finds_ea_desktop_launcher_logs(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        logs_dir = tmp_path / "home" / ".local" / "share" / "Electronic Arts" / "EA Desktop" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EADesktop.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1
        assert logs[0].description == "EA App launcher log"

    def test_finds_programdata_logs(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        logs_dir = tmp_path / "ProgramData" / "EA Desktop" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EABackgroundService.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1

    def test_ignores_small_launcher_logs(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        logs_dir = tmp_path / "home" / ".local" / "share" / "Electronic Arts" / "EA Desktop" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0


class TestEaLauncherCache:
    def test_finds_ea_desktop_cache(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        cache_dir = tmp_path / "home" / ".local" / "share" / "EADesktop" / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "data.bin").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 1
        assert cache[0].description == "EADesktop cache"

    def test_finds_ea_launch_helper_cache(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        cache_dir = tmp_path / "home" / ".local" / "share" / "EALaunchHelper" / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "qml.cache").write_bytes(b"\x00" * 2048)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 1
        assert cache[0].description == "EALaunchHelper cache"

    def test_finds_both_caches(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        appdata = tmp_path / "home" / ".local" / "share"
        for dir_name in ("EADesktop", "EALaunchHelper"):
            cache_dir = appdata / dir_name / "cache"
            cache_dir.mkdir(parents=True)
            (cache_dir / "data.bin").write_bytes(b"\x00" * 1024)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 2

    def test_ignores_empty_cache(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path)
        cache_dir = tmp_path / "home" / ".local" / "share" / "EADesktop" / "cache"
        cache_dir.mkdir(parents=True)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 0


class TestEaUnicode:
    def test_cyrillic_game_name(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"Игра Тест": {"_CommonRedist": ["vcredist.exe"]}},
        )
        entries = list(client.scan_junk())
        assert len(entries) == 1

    def test_cjk_game_name(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"ゲームテスト": {"redist": ["setup.msi"]}},
        )
        entries = list(client.scan_junk())
        assert len(entries) == 1


class TestEaEdgeCases:
    def test_not_installed_yields_nothing(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert entries == []

    def test_exe_outside_redist_ignored(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"BF2042": {"Binaries": ["game.exe"]}})
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0

    def test_empty_game_dir(self, tmp_path: Path):
        platform, client = _make_ea_env(tmp_path, games={"EmptyGame": {"": []}})
        entries = list(client.scan_junk())
        assert entries == []

    def test_exclusion_filters(self, tmp_path: Path):
        platform, client = _make_ea_env(
            tmp_path,
            games={"Battlefield 2042": {"_CommonRedist": ["vcredist.exe"]}},
        )
        exclusions = ExclusionRegistry()
        exclusions.add("Battlefield 2042", "test exclusion")
        client_with_excl = EaAppClient(platform, exclusions)
        safe_entries = list(client_with_excl.scan_safe())
        assert len(safe_entries) == 0

    def test_both_ea_and_origin_dirs_scanned(self, tmp_path: Path):
        home = tmp_path / "home"
        program_files = tmp_path / "ProgramFiles"

        ea_game = program_files / "EA Games" / "BF2042"
        ea_game.mkdir(parents=True)
        redist = ea_game / "_CommonRedist"
        redist.mkdir()
        (redist / "vcredist.exe").write_bytes(b"\x00" * 1024)

        origin_game = program_files / "Origin Games" / "MassEffect"
        origin_game.mkdir(parents=True)
        redist2 = origin_game / "_CommonRedist"
        redist2.mkdir()
        (redist2 / "dxsetup.exe").write_bytes(b"\x00" * 1024)

        (home / ".local" / "share" / "Electronic Arts" / "EA Desktop").mkdir(parents=True)

        platform = FakePlatformAdapter(
            home_dir=home,
            program_files_dirs=[program_files],
            programdata_dir=tmp_path / "ProgramData",
        )
        client = EaAppClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist_entries) == 2
