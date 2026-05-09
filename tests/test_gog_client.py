from pathlib import Path

from steamcleaner.clients.gog import GogClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter

_REGISTRY_GAMES_PATH = r"SOFTWARE\WOW6432Node\GOG.com\Games"


def _make_gog_env(
    tmp_path: Path,
    games: dict[str, dict[str, list[str]]] | None = None,
    game_dir_name: str = "GOG Games",
    galaxy_exists: bool = True,
    registry_games: dict[str, Path] | None = None,
) -> tuple[FakePlatformAdapter, GogClient]:
    home = tmp_path / "home"
    programdata = tmp_path / "ProgramData"
    program_files = tmp_path / "ProgramFiles"

    if galaxy_exists:
        (programdata / "GOG.com" / "Galaxy").mkdir(parents=True)

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
        game_ids = []
        for game_id, install_path in registry_games.items():
            game_ids.append(game_id)
            platform.set_registry("HKLM", rf"{_REGISTRY_GAMES_PATH}\{game_id}", "path", str(install_path))
        platform.set_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH, game_ids)

    return platform, GogClient(platform, ExclusionRegistry())


class TestGogDetection:
    def test_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert not client.is_installed()

    def test_installed(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        assert client.is_installed()

    def test_name(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        assert client.name == "GOG Galaxy"


class TestGogGameDiscovery:
    def test_discovers_from_gog_games_dir(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"": []}})
        paths = client._game_install_paths()
        assert any(path.name == "Witcher 3" for path in paths)

    def test_discovers_from_galaxy_games_dir(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Cyberpunk 2077": {"": []}}, game_dir_name="GOG Galaxy/Games")
        paths = client._game_install_paths()
        assert any(path.name == "Cyberpunk 2077" for path in paths)

    def test_discovers_from_registry(self, tmp_path: Path):
        game_dir = tmp_path / "CustomGames" / "Witcher3"
        game_dir.mkdir(parents=True)
        platform, client = _make_gog_env(tmp_path, registry_games={"1495134320": game_dir})
        paths = client._game_install_paths()
        assert game_dir in paths

    def test_registry_nonexistent_path_skipped(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, registry_games={"12345": tmp_path / "nonexistent"})
        paths = client._game_install_paths()
        assert len(paths) == 0

    def test_no_duplicate_paths(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"": []}})
        game_path = tmp_path / "ProgramFiles" / "GOG Games" / "Witcher 3"
        platform.set_registry_subkeys("HKLM", _REGISTRY_GAMES_PATH, ["1495134320"])
        platform.set_registry("HKLM", rf"{_REGISTRY_GAMES_PATH}\1495134320", "path", str(game_path))
        paths = client._game_install_paths()
        assert paths.count(game_path) == 1


class TestGogRedistScan:
    def test_finds_common_redist(self, tmp_path: Path):
        platform, client = _make_gog_env(
            tmp_path,
            games={"Witcher 3": {"_CommonRedist": ["vcredist.exe", "dxsetup.cab"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 1
        assert redist[0].size_bytes == 2048
        assert redist[0].client_name == "GOG Galaxy"

    def test_ignores_non_junk_extensions(self, tmp_path: Path):
        platform, client = _make_gog_env(
            tmp_path,
            games={"Witcher 3": {"_CommonRedist": ["readme.txt"]}},
        )
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0

    def test_exe_outside_redist_ignored(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"bin": ["witcher3.exe"]}})
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert len(redist) == 0


class TestGogDumpScan:
    def test_finds_crash_dumps(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "GOG Games" / "Witcher 3"
        (game_dir / "crash.dmp").write_bytes(b"\x00" * 512)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 1

    def test_ignores_zero_size_dumps(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "GOG Games" / "Witcher 3"
        (game_dir / "empty.dmp").write_bytes(b"")
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 0


class TestGogLogScan:
    def test_finds_large_game_logs(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"": []}})
        game_dir = tmp_path / "ProgramFiles" / "GOG Games" / "Witcher 3"
        (game_dir / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1

    def test_finds_launcher_logs(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        logs_dir = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "galaxy.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 1
        assert logs[0].description == "GOG Galaxy launcher log"

    def test_ignores_small_launcher_logs(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        logs_dir = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(client.scan_junk())
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert len(logs) == 0


class TestGogCrashdumps:
    def test_finds_crashdumps(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        crashdumps = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "crashdumps"
        crashdumps.mkdir(parents=True)
        (crashdumps / "dump.dmp").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 1
        assert dumps[0].description == "GOG Galaxy crash dumps"

    def test_ignores_empty_crashdumps(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        crashdumps = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "crashdumps"
        crashdumps.mkdir(parents=True)
        entries = list(client.scan_junk())
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert len(dumps) == 0


class TestGogWebcache:
    def test_finds_webcache(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        webcache = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "webcache"
        webcache.mkdir(parents=True)
        (webcache / "cache.bin").write_bytes(b"\x00" * 4096)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 1

    def test_ignores_empty_webcache(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path)
        webcache = tmp_path / "ProgramData" / "GOG.com" / "Galaxy" / "webcache"
        webcache.mkdir(parents=True)
        entries = list(client.scan_junk())
        cache = [entry for entry in entries if entry.category == JunkCategory.SHADER_CACHE]
        assert len(cache) == 0


class TestGogUnicode:
    def test_cyrillic_game_name(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Ведьмак 3": {"_CommonRedist": ["vcredist.exe"]}})
        entries = list(client.scan_junk())
        assert len(entries) == 1

    def test_cjk_game_name(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"ゲームテスト": {"redist": ["setup.msi"]}})
        entries = list(client.scan_junk())
        assert len(entries) == 1


class TestGogEdgeCases:
    def test_not_installed_yields_nothing(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = GogClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert entries == []

    def test_empty_game_dir(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"EmptyGame": {"": []}})
        entries = list(client.scan_junk())
        assert entries == []

    def test_exclusion_filters(self, tmp_path: Path):
        platform, client = _make_gog_env(tmp_path, games={"Witcher 3": {"_CommonRedist": ["vcredist.exe"]}})
        exclusions = ExclusionRegistry()
        exclusions.add("Witcher 3", "test exclusion")
        client_with_excl = GogClient(platform, exclusions)
        safe_entries = list(client_with_excl.scan_safe())
        assert len(safe_entries) == 0
