import threading
from pathlib import Path

from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.models.junk import JunkEntry
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry


def _make_steam_tree(tmp_path: Path) -> FakePlatformAdapter:
    steam = tmp_path / "Steam"
    common = steam / "steamapps" / "common"
    game = common / "TestGame" / "_CommonRedist"
    game.mkdir(parents=True)
    (game / "setup.exe").write_bytes(b"\x00" * 1024)
    return FakePlatformAdapter(install_path=steam)


class TestScanEngineCallbacks:
    def test_progress_callback_called(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg))
        assert_that(any("Scanning" in msg for msg in messages)).is_true()

    def test_on_found_callback_called(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        found: list[JunkEntry] = []
        engine.scan(on_found=lambda entry: found.append(entry))
        assert_that(found).is_not_empty()

    def test_progress_reports_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg))
        assert_that(any("not installed" in msg for msg in messages)).is_true()

    def test_progress_reports_count(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg))
        assert_that(any("found" in msg for msg in messages)).is_true()

    def test_cancel_stops_mid_entry(self, tmp_path: Path):
        steam = tmp_path / "Steam"
        common = steam / "steamapps" / "common"
        for i in range(10):
            game = common / f"Game{i}" / "_CommonRedist"
            game.mkdir(parents=True)
            (game / "setup.exe").write_bytes(b"\x00" * 1024)

        platform = FakePlatformAdapter(install_path=steam)
        engine = ScanEngine(platform, ExclusionRegistry())
        cancel = threading.Event()
        found: list[JunkEntry] = []

        def on_found(entry: JunkEntry):
            found.append(entry)
            if len(found) >= 2:
                cancel.set()

        result = engine.scan(on_found=on_found, cancel=cancel)
        assert_that(len(result.entries)).is_less_than(10)


class TestCustomPaths:
    def test_scans_custom_directory(self, tmp_path: Path):
        custom = tmp_path / "CustomGames"
        game = custom / "MyGame" / "_CommonRedist"
        game.mkdir(parents=True)
        (game / "setup.exe").write_bytes(b"\x00" * 512)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        result = engine.scan(custom_paths=[custom])
        assert_that(any(entry.client_name == "Custom" for entry in result.entries)).is_true()
        assert_that(any("setup.exe" in str(entry.path) for entry in result.entries)).is_true()

    def test_skips_nonexistent_custom_path(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        result = engine.scan(custom_paths=[tmp_path / "nonexistent"])
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_equal_to([])

    def test_custom_path_progress_callback(self, tmp_path: Path):
        custom = tmp_path / "MyLibrary"
        game = custom / "SomeGame" / "redist"
        game.mkdir(parents=True)
        (game / "installer.exe").write_bytes(b"\x00" * 256)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg), custom_paths=[custom])
        assert_that(any("MyLibrary" in msg for msg in messages)).is_true()

    def test_custom_path_skips_non_matching(self, tmp_path: Path):
        custom = tmp_path / "Library"
        game = custom / "MyGame" / "gamedata"
        game.mkdir(parents=True)
        (game / "save.dat").write_bytes(b"\x00" * 256)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        result = engine.scan(custom_paths=[custom])
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_equal_to([])

    def test_custom_path_cancel(self, tmp_path: Path):
        custom = tmp_path / "Library"
        for i in range(10):
            game = custom / f"Game{i}" / "_CommonRedist"
            game.mkdir(parents=True)
            (game / "setup.exe").write_bytes(b"\x00" * 256)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        cancel = threading.Event()
        cancel.set()
        result = engine.scan(custom_paths=[custom], cancel=cancel)
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_equal_to([])

    def test_custom_path_respects_exclusions(self, tmp_path: Path):
        custom = tmp_path / "Library"
        game = custom / "MyGame" / "_CommonRedist"
        game.mkdir(parents=True)
        target = game / "setup.exe"
        target.write_bytes(b"\x00" * 256)

        exclusions = ExclusionRegistry()
        exclusions.add("MyGame", "test exclusion")

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, exclusions)
        result = engine.scan(custom_paths=[custom])
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_equal_to([])

    def test_custom_path_on_found_callback(self, tmp_path: Path):
        custom = tmp_path / "Library"
        game = custom / "MyGame" / "_CommonRedist"
        game.mkdir(parents=True)
        (game / "setup.exe").write_bytes(b"\x00" * 256)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        found: list[JunkEntry] = []
        engine.scan(on_found=lambda entry: found.append(entry), custom_paths=[custom])
        custom_found = [entry for entry in found if entry.client_name == "Custom"]
        assert_that(custom_found).is_not_empty()

    def test_custom_path_skips_files_in_root(self, tmp_path: Path):
        custom = tmp_path / "Library"
        custom.mkdir()
        (custom / "readme.txt").write_bytes(b"data")

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        result = engine.scan(custom_paths=[custom])
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_equal_to([])
