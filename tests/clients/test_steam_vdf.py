from pathlib import Path

from helpers import FakePlatformAdapter

from steamcleaner.clients.steam import SteamClient, parse_library_folders_vdf
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import dir_size


def _vdf_escape(path: Path) -> str:
    """Escape a path for VDF format (double backslashes on Windows)."""
    return str(path).replace("\\", "\\\\")


class TestParseLibraryFoldersVdf:
    def test_parses_valid_vdf(self, tmp_path: Path):
        vdf = tmp_path / "libraryfolders.vdf"
        library = tmp_path / "SteamLibrary"
        library.mkdir()
        escaped = _vdf_escape(library)
        vdf.write_text(f'"libraryfolders"\n{{\n  "0"\n  {{\n    "path"\t\t"{escaped}"\n  }}\n}}')
        paths = parse_library_folders_vdf(vdf)
        assert library in paths

    def test_missing_file_returns_empty(self, tmp_path: Path):
        result = parse_library_folders_vdf(tmp_path / "nonexistent.vdf")
        assert result == []

    def test_skips_nonexistent_paths(self, tmp_path: Path):
        vdf = tmp_path / "libraryfolders.vdf"
        vdf.write_text('"libraryfolders"\n{\n  "0"\n  {\n    "path"\t\t"/nonexistent/path"\n  }\n}')
        result = parse_library_folders_vdf(vdf)
        assert result == []

    def test_multiple_libraries(self, tmp_path: Path):
        lib_a = tmp_path / "LibA"
        lib_b = tmp_path / "LibB"
        lib_a.mkdir()
        lib_b.mkdir()
        vdf = tmp_path / "libraryfolders.vdf"
        escaped_a = _vdf_escape(lib_a)
        escaped_b = _vdf_escape(lib_b)
        content = (
            '"libraryfolders"\n{\n'
            f'  "0"\n  {{\n    "path"\t\t"{escaped_a}"\n  }}\n'
            f'  "1"\n  {{\n    "path"\t\t"{escaped_b}"\n  }}\n'
            "}"
        )
        vdf.write_text(content)
        paths = parse_library_folders_vdf(vdf)
        assert lib_a in paths
        assert lib_b in paths


class TestDirSize:
    def test_calculates_total(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 100)
        (tmp_path / "b.txt").write_bytes(b"\x00" * 200)
        assert dir_size(tmp_path) == 300

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert dir_size(empty) == 0

    def test_nested_files(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.bin").write_bytes(b"\x00" * 500)
        assert dir_size(tmp_path) == 500


class TestSteamNotInstalled:
    def test_library_folders_empty_without_install(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert entries == []

    def test_game_install_paths_returns_empty(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert client.game_install_paths() == []


class TestSteamClientLibraries:
    def test_library_folders_from_vdf(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        common = steam / "steamapps" / "common"
        common.mkdir(parents=True)

        extra_lib = tmp_path / "ExtraLib"
        extra_common = extra_lib / "steamapps" / "common"
        extra_common.mkdir(parents=True)

        vdf = steam / "steamapps" / "libraryfolders.vdf"
        escaped = _vdf_escape(extra_lib)
        vdf.write_text(f'"libraryfolders"\n{{\n  "0"\n  {{\n    "path"\t\t"{escaped}"\n  }}\n}}')

        game = extra_common / "TestGame" / "_CommonRedist"
        game.mkdir(parents=True)
        (game / "setup.exe").write_bytes(b"\x00" * 1024)

        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.path.is_relative_to(extra_lib)]
        assert len(redist_entries) > 0

    def test_scan_library_without_common_dir(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category.value == "redistributable"]
        assert len(redist) == 0

    def test_scan_handles_empty_common(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category.value == "redistributable"]
        assert len(redist) == 0

    def test_scan_skips_files_in_common(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        common = steam / "steamapps" / "common"
        common.mkdir(parents=True)
        (common / "not_a_dir.txt").write_bytes(b"data")
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert all("not_a_dir" not in str(entry.path) for entry in entries)


class TestSteamRedistFiltering:
    def test_skips_non_matching_subdirs(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        common = steam / "steamapps" / "common"
        game = common / "TestGame"
        game.mkdir(parents=True)
        non_redist = game / "gamedata"
        non_redist.mkdir()
        (non_redist / "setup.exe").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist = [entry for entry in entries if entry.category.value == "redistributable"]
        assert len(redist) == 0


class TestSteamGameLogs:
    def test_ignores_small_game_logs(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        common = steam / "steamapps" / "common"
        game = common / "TestGame"
        game.mkdir(parents=True)
        (game / "output.log").write_bytes(b"\x00" * 100)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        log_entries = [entry for entry in entries if entry.category.value == "old_log"]
        assert len(log_entries) == 0


class TestSteamShaderCache:
    def test_finds_shader_cache(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        shader = steam / "steamapps" / "shadercache" / "730"
        shader.mkdir(parents=True)
        (shader / "cache.bin").write_bytes(b"\x00" * 4096)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [entry for entry in entries if entry.category.value == "shader_cache"]
        assert len(shader_entries) == 1
        assert shader_entries[0].size_bytes == 4096
        assert "730" in shader_entries[0].description

    def test_finds_multiple_shader_caches(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        for app_id in ("730", "570"):
            cache_dir = steam / "steamapps" / "shadercache" / app_id
            cache_dir.mkdir(parents=True)
            (cache_dir / "data.bin").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [entry for entry in entries if entry.category.value == "shader_cache"]
        assert len(shader_entries) == 2

    def test_no_shader_cache_dir(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader = [entry for entry in entries if entry.category.value == "shader_cache"]
        assert len(shader) == 0

    def test_empty_shader_app_dir(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        shader = steam / "steamapps" / "shadercache" / "123"
        shader.mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        shader_entries = [entry for entry in entries if entry.category.value == "shader_cache"]
        assert len(shader_entries) == 0


class TestSteamDumps:
    def test_finds_steam_dumps(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        dumps = steam / "dumps"
        dumps.mkdir()
        (dumps / "crash_2026-01-01.dmp").write_bytes(b"\x00" * 2048)
        (dumps / "assert_2026-01-02.mdmp").write_bytes(b"\x00" * 1024)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category.value == "crash_dump"]
        assert len(dump_entries) == 1
        assert dump_entries[0].path == dumps
        assert dump_entries[0].size_bytes == 3072

    def test_ignores_empty_dumps_dir(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        (steam / "dumps").mkdir()
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category.value == "crash_dump"]
        assert len(dump_entries) == 0

    def test_no_dumps_dir(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        dump_entries = [entry for entry in entries if entry.category.value == "crash_dump"]
        assert len(dump_entries) == 0


class TestConfigVdfFallback:
    def test_fallback_finds_legacy_folders(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)

        extra_lib = tmp_path / "ExtraLib"
        extra_common = extra_lib / "steamapps" / "common"
        extra_common.mkdir(parents=True)

        game = extra_common / "TestGame" / "_CommonRedist"
        game.mkdir(parents=True)
        (game / "setup.exe").write_bytes(b"\x00" * 1024)

        config_dir = steam / "config"
        config_dir.mkdir()
        escaped = _vdf_escape(extra_lib)
        config_vdf = config_dir / "config.vdf"
        config_vdf.write_text(
            '"InstallConfigStore"\n{\n'
            '  "Software"\n  {\n'
            '    "Valve"\n    {\n'
            '      "Steam"\n      {\n'
            f'        "BaseInstallFolder_1"\t\t"{escaped}"\n'
            "      }\n    }\n  }\n}"
        )

        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        redist_entries = [entry for entry in entries if entry.path.is_relative_to(extra_lib)]
        assert len(redist_entries) > 0

    def test_fallback_skips_nonexistent_paths(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)

        config_dir = steam / "config"
        config_dir.mkdir()
        config_vdf = config_dir / "config.vdf"
        config_vdf.write_text(
            '"InstallConfigStore"\n{\n'
            '  "Software"\n  {\n'
            '    "Valve"\n    {\n'
            '      "Steam"\n      {\n'
            '        "BaseInstallFolder_1"\t\t"/nonexistent/path"\n'
            "      }\n    }\n  }\n}"
        )

        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        paths = client.game_install_paths()
        assert all(not str(path).startswith("/nonexistent") for path in paths)

    def test_modern_vdf_takes_priority(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)

        modern_lib = tmp_path / "ModernLib"
        modern_common = modern_lib / "steamapps" / "common"
        modern_common.mkdir(parents=True)
        (modern_common / "SomeGame").mkdir()

        legacy_lib = tmp_path / "LegacyLib"
        (legacy_lib / "steamapps" / "common").mkdir(parents=True)

        vdf = steam / "steamapps" / "libraryfolders.vdf"
        escaped_modern = _vdf_escape(modern_lib)
        vdf.write_text(f'"libraryfolders"\n{{\n  "0"\n  {{\n    "path"\t\t"{escaped_modern}"\n  }}\n}}')

        config_dir = steam / "config"
        config_dir.mkdir()
        escaped_legacy = _vdf_escape(legacy_lib)
        config_vdf = config_dir / "config.vdf"
        config_vdf.write_text(
            '"InstallConfigStore"\n{\n'
            '  "Software"\n  {\n'
            '    "Valve"\n    {\n'
            '      "Steam"\n      {\n'
            f'        "BaseInstallFolder_1"\t\t"{escaped_legacy}"\n'
            "      }\n    }\n  }\n}"
        )

        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        install_paths = client.game_install_paths()
        modern_found = any(path.is_relative_to(modern_lib) for path in install_paths)
        assert modern_found

    def test_no_config_vdf(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        (steam / "steamapps" / "common").mkdir(parents=True)
        platform = FakePlatformAdapter(install_path=steam)
        client = SteamClient(platform, ExclusionRegistry())
        entries = list(client.scan_junk())
        assert isinstance(entries, list)
