import re
import threading
from pathlib import Path

from assertpy2 import assert_that

from steamcleaner.clients.shared import (
    REDIST_DIR_RE,
    find_redist_root,
    has_redist_ancestor,
    scan_cache_dir,
    scan_game,
    scan_launcher_logs,
)
from steamcleaner.models.junk import JunkCategory


class TestHasRedistAncestor:
    def test_file_in_common_redist(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist" / "vcredist"
        redist.mkdir(parents=True)
        file = redist / "setup.exe"
        file.touch()
        assert_that(has_redist_ancestor(file, game)).is_true()

    def test_file_in_game_root(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        file = game / "game.exe"
        file.touch()
        assert_that(has_redist_ancestor(file, game)).is_false()

    def test_nested_redist_dirs(self, tmp_path: Path):
        game = tmp_path / "Game"
        nested = game / "support" / "directx"
        nested.mkdir(parents=True)
        file = nested / "dxsetup.exe"
        file.touch()
        assert_that(has_redist_ancestor(file, game)).is_true()

    def test_custom_pattern(self, tmp_path: Path):
        pattern = re.compile(r"prerequisites", re.IGNORECASE)
        game = tmp_path / "Game"
        prereq = game / "Prerequisites"
        prereq.mkdir(parents=True)
        file = prereq / "installer.exe"
        file.touch()
        assert_that(has_redist_ancestor(file, game, pattern)).is_true()

    def test_custom_pattern_no_match(self, tmp_path: Path):
        pattern = re.compile(r"prerequisites", re.IGNORECASE)
        game = tmp_path / "Game"
        regular = game / "data"
        regular.mkdir(parents=True)
        file = regular / "game.exe"
        file.touch()
        assert_that(has_redist_ancestor(file, game, pattern)).is_false()


class TestFindRedistRoot:
    def test_returns_topmost_redist(self, tmp_path: Path):
        game = tmp_path / "Game"
        nested = game / "support" / "directx" / "x64"
        nested.mkdir(parents=True)
        file = nested / "dxsetup.exe"
        file.touch()
        root = find_redist_root(file, game)
        assert_that(root).is_equal_to(game / "support")

    def test_single_redist_dir(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        file = redist / "setup.cab"
        file.touch()
        root = find_redist_root(file, game)
        assert_that(root).is_equal_to(redist)

    def test_no_redist_returns_none(self, tmp_path: Path):
        game = tmp_path / "Game"
        data = game / "data"
        data.mkdir(parents=True)
        file = data / "config.ini"
        file.touch()
        root = find_redist_root(file, game)
        assert_that(root).is_none()

    def test_custom_pattern(self, tmp_path: Path):
        pattern = re.compile(REDIST_DIR_RE.pattern + r"|prerequisites", re.IGNORECASE)
        game = tmp_path / "Game"
        prereq = game / "Prerequisites" / "EasyAntiCheat"
        prereq.mkdir(parents=True)
        file = prereq / "installer.msi"
        file.touch()
        root = find_redist_root(file, game, pattern)
        assert_that(root).is_equal_to(game / "Prerequisites")


class TestScanGame:
    def test_finds_crash_dumps(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        (game / "crash.dmp").write_bytes(b"\x00" * 512)
        (game / "mini.mdmp").write_bytes(b"\x00" * 256)
        entries = list(scan_game(game, "TestClient", lambda: False))
        dumps = [entry for entry in entries if entry.category == JunkCategory.CRASH_DUMP]
        assert_that(dumps).is_length(2)

    def test_skips_empty_dumps(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        (game / "empty.dmp").write_bytes(b"")
        entries = list(scan_game(game, "TestClient", lambda: False))
        assert_that(entries).is_length(0)

    def test_finds_large_logs(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        (game / "output.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(scan_game(game, "TestClient", lambda: False))
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(1)

    def test_skips_small_logs(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        (game / "debug.log").write_bytes(b"\x00" * 100)
        entries = list(scan_game(game, "TestClient", lambda: False))
        logs = [entry for entry in entries if entry.category == JunkCategory.OLD_LOG]
        assert_that(logs).is_length(0)

    def test_finds_redist_directory(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist" / "vcredist"
        redist.mkdir(parents=True)
        (redist / "vc_redist.x64.exe").write_bytes(b"\x00" * 2048)
        entries = list(scan_game(game, "TestClient", lambda: False))
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(1)
        assert_that(redist_entries[0].path).is_equal_to(game / "_CommonRedist")

    def test_deduplicates_redist_entries(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist" / "vcredist"
        redist.mkdir(parents=True)
        (redist / "vc_redist.x64.exe").write_bytes(b"\x00" * 1024)
        (redist / "vc_redist.x86.exe").write_bytes(b"\x00" * 1024)
        sub = game / "_CommonRedist" / "directx"
        sub.mkdir(parents=True)
        (sub / "dxsetup.exe").write_bytes(b"\x00" * 1024)
        entries = list(scan_game(game, "TestClient", lambda: False))
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(1)

    def test_cancel_stops_iteration(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        for index in range(100):
            (game / f"crash_{index}.dmp").write_bytes(b"\x00" * 100)
        cancel = threading.Event()
        cancel.set()
        entries = list(scan_game(game, "TestClient", cancel.is_set))
        assert_that(entries).is_length(0)

    def test_custom_pattern_epic_prerequisites(self, tmp_path: Path):
        pattern = re.compile(REDIST_DIR_RE.pattern + r"|prerequisites", re.IGNORECASE)
        game = tmp_path / "Game"
        prereq = game / "Prerequisites"
        prereq.mkdir(parents=True)
        (prereq / "EasyAntiCheatSetup.exe").write_bytes(b"\x00" * 4096)
        entries = list(scan_game(game, "Epic Games", lambda: False, pattern=pattern))
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(1)

    def test_uses_client_name_in_entries(self, tmp_path: Path):
        game = tmp_path / "Game"
        game.mkdir()
        (game / "crash.dmp").write_bytes(b"\x00" * 100)
        entries = list(scan_game(game, "MyClient", lambda: False))
        assert_that(entries[0].client_name).is_equal_to("MyClient")

    def test_ignores_non_junk_extensions_in_redist(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "readme.txt").write_bytes(b"\x00" * 1024)
        entries = list(scan_game(game, "TestClient", lambda: False))
        assert_that(entries).is_length(0)

    def test_skips_redist_dir_with_zero_size(self, tmp_path: Path):
        game = tmp_path / "Game"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        # Junk-extension file present but empty -> redist junk_size is 0, nothing yielded.
        (redist / "empty.exe").write_bytes(b"")
        entries = list(scan_game(game, "TestClient", lambda: False))
        redist_entries = [entry for entry in entries if entry.category == JunkCategory.REDISTRIBUTABLE]
        assert_that(redist_entries).is_length(0)


class TestScanLauncherLogs:
    def test_finds_large_log_files(self, tmp_path: Path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "launcher.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        entries = list(scan_launcher_logs([logs_dir], "TestClient", lambda: False, "test log"))
        assert_that(entries).is_length(1)
        assert_that(entries[0].category).is_equal_to(JunkCategory.OLD_LOG)
        assert_that(entries[0].game_root).is_equal_to(tmp_path)

    def test_skips_small_log_files(self, tmp_path: Path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "small.log").write_bytes(b"\x00" * 100)
        entries = list(scan_launcher_logs([logs_dir], "TestClient", lambda: False, "test log"))
        assert_that(entries).is_length(0)

    def test_skips_nonexistent_dirs(self, tmp_path: Path):
        entries = list(scan_launcher_logs([tmp_path / "nope"], "TestClient", lambda: False, "test log"))
        assert_that(entries).is_length(0)

    def test_uses_explicit_game_root(self, tmp_path: Path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "launcher.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        custom_root = tmp_path / "custom"
        custom_root.mkdir()
        entries = list(scan_launcher_logs([logs_dir], "TestClient", lambda: False, "test log", game_root=custom_root))
        assert_that(entries[0].game_root).is_equal_to(custom_root)

    def test_cancel_stops_iteration(self, tmp_path: Path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        for index in range(10):
            (logs_dir / f"log_{index}.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
        cancel = threading.Event()
        cancel.set()
        entries = list(scan_launcher_logs([logs_dir], "TestClient", cancel.is_set, "test log"))
        assert_that(entries).is_length(0)


class TestScanCacheDir:
    def test_yields_entry_for_nonempty_dir(self, tmp_path: Path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "data.bin").write_bytes(b"\x00" * 1024)
        entries = list(
            scan_cache_dir(
                cache,
                JunkCategory.SHADER_CACHE,
                "TestClient",
                "test cache",
                lambda: False,
            )
        )
        assert_that(entries).is_length(1)
        assert_that(entries[0].category).is_equal_to(JunkCategory.SHADER_CACHE)
        assert_that(entries[0].size_bytes).is_equal_to(1024)
        assert_that(entries[0].game_root).is_equal_to(tmp_path)

    def test_skips_nonexistent_dir(self, tmp_path: Path):
        entries = list(
            scan_cache_dir(
                tmp_path / "nope",
                JunkCategory.SHADER_CACHE,
                "TestClient",
                "test",
                lambda: False,
            )
        )
        assert_that(entries).is_length(0)

    def test_skips_empty_dir(self, tmp_path: Path):
        cache = tmp_path / "cache"
        cache.mkdir()
        entries = list(
            scan_cache_dir(
                cache,
                JunkCategory.SHADER_CACHE,
                "TestClient",
                "test",
                lambda: False,
            )
        )
        assert_that(entries).is_length(0)

    def test_skips_when_cancelled(self, tmp_path: Path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "data.bin").write_bytes(b"\x00" * 1024)
        cancel = threading.Event()
        cancel.set()
        entries = list(
            scan_cache_dir(
                cache,
                JunkCategory.SHADER_CACHE,
                "TestClient",
                "test",
                cancel.is_set,
            )
        )
        assert_that(entries).is_length(0)

    def test_uses_explicit_game_root(self, tmp_path: Path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "data.bin").write_bytes(b"\x00" * 512)
        custom_root = tmp_path / "root"
        custom_root.mkdir()
        entries = list(
            scan_cache_dir(
                cache,
                JunkCategory.CRASH_DUMP,
                "TestClient",
                "test",
                lambda: False,
                game_root=custom_root,
            )
        )
        assert_that(entries[0].game_root).is_equal_to(custom_root)
