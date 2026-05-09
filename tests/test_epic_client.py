import json
from pathlib import Path

from steamcleaner.clients.epic import EpicClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter


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
        assert not client.is_installed()

    def test_installed(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        assert client.is_installed()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        assert client.name == "Epic Games"


class TestEpicGameDiscovery:
    def test_discovers_from_program_files(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        paths = client._game_install_paths()
        assert any(path.name == "Fortnite" for path in paths)

    def test_skips_launcher_dir(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Launcher": {"": []}, "Fortnite": {"": []}})
        paths = client._game_install_paths()
        names = [path.name for path in paths]
        assert "Launcher" not in names
        assert "Fortnite" in names

    def test_discovers_from_manifests(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "MyGame"
        game_dir.mkdir(parents=True)
        platform, client = _make_epic_env(tmp_path, manifest_locations=[game_dir])
        paths = client._game_install_paths()
        assert game_dir in paths

    def test_manifest_nonexistent_path_skipped(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, manifest_locations=[tmp_path / "nonexistent" / "game"])
        paths = client._game_install_paths()
        assert len(paths) == 0

    def test_manifest_invalid_json_skipped(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        programdata = tmp_path / "ProgramData"
        manifests = programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        (manifests / "broken.item").write_text("{invalid json", encoding="utf-8")
        paths = client._game_install_paths()
        assert len(paths) == 0

    def test_no_duplicate_paths(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_path = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        programdata = tmp_path / "ProgramData"
        manifests = programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        manifests.mkdir(parents=True)
        manifest = {"InstallLocation": str(game_path)}
        (manifests / "fortnite.item").write_text(json.dumps(manifest), encoding="utf-8")
        paths = client._game_install_paths()
        assert paths.count(game_path) == 1


class TestEpicRedistScan:
    def test_finds_redist(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1
        assert redist[0].size_bytes == 2048
        assert redist[0].client_name == "Epic Games"

    def test_finds_prerequisites(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"Prerequisites": ["EpicPrereqSetup.exe"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["readme.txt", "notes.pdf"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0

    def test_nested_redist_no_duplicates(self, tmp_path: Path):
        platform, client = _make_epic_env(
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
        assert len(redist) == 1
        assert "__Installer" in str(redist[0].path)


class TestEpicDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        (game_dir / "mini.mdmp").write_bytes(b"\x00" * 256)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 2

    def test_ignores_zero_size_dumps(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "empty.dmp").write_bytes(b"")
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 0


class TestEpicLogScan:
    def test_finds_large_game_logs(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1

    def test_ignores_small_game_logs(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "Epic Games" / "Fortnite"
        (game_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0

    def test_finds_launcher_logs(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        logs_dir = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "EpicGamesLauncher.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1
        assert logs[0].description == "Epic Games Launcher log"

    def test_ignores_small_launcher_logs(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        logs_dir = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "Logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0


class TestEpicWebcache:
    def test_finds_webcache(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache"
        webcache.mkdir(parents=True)
        (webcache / "cache_data.bin").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 1
        assert cache[0].size_bytes == 4096

    def test_finds_webcache_with_port_suffix(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache_4430"
        webcache.mkdir(parents=True)
        (webcache / "data.bin").write_bytes(b"\x00" * 2048)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 1
        assert "webcache_4430" in str(cache[0].path)

    def test_finds_multiple_webcache_dirs(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        saved = home / ".local" / "share" / "EpicGamesLauncher" / "Saved"
        for name in ("webcache", "webcache_4430", "webcache_8888"):
            cache_dir = saved / name
            cache_dir.mkdir(parents=True)
            (cache_dir / "data.bin").write_bytes(b"\x00" * 1024)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 3

    def test_ignores_empty_webcache(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path)
        home = tmp_path / "home"
        webcache = home / ".local" / "share" / "EpicGamesLauncher" / "Saved" / "webcache"
        webcache.mkdir(parents=True)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 0


class TestEpicUnicode:
    def test_cyrillic_game_name(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"Игра Тест": {"_CommonRedist": ["vcredist.exe"]}},
        )
        entries = list(client.scan_junk())
        assert len(entries) == 1

    def test_cjk_game_name(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"ゲームテスト": {"redist": ["setup.msi"]}},
        )
        entries = list(client.scan_junk())
        assert len(entries) == 1


class TestEpicEdgeCases:
    def test_not_installed_yields_nothing(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = EpicClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert entries == []

    def test_empty_game_dir(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"EmptyGame": {"": []}})
        entries = list(client.scan_junk())
        assert entries == []

    def test_exe_outside_redist_ignored(self, tmp_path: Path):
        platform, client = _make_epic_env(tmp_path, games={"Fortnite": {"Binaries": ["game.exe"]}})
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0

    def test_exclusion_filters(self, tmp_path: Path):
        platform, client = _make_epic_env(
            tmp_path,
            games={"Fortnite": {"_CommonRedist": ["vcredist.exe"]}},
        )
        exclusions = ExclusionRegistry()
        exclusions.add("Fortnite", "test exclusion")
        client_with_excl = EpicClient(platform, exclusions)
        safe_entries = list(client_with_excl.scan_safe())
        assert len(safe_entries) == 0
