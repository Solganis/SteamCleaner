import os
import threading
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter, write_app_manifest

from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from pathlib import Path, PurePath

    from steamcleaner.models.junk import JunkEntry


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

    def test_cancel_while_entry_in_flight_discards_it(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        cancel = threading.Event()
        found: list[JunkEntry] = []

        def cancel_during_exclusion_check(path: PurePath) -> bool:
            cancel.set()
            return False

        with patch.object(ExclusionRegistry, "is_excluded", side_effect=cancel_during_exclusion_check):
            result = engine.scan(on_found=found.append, cancel=cancel)
        assert_that(result.entries).is_empty()
        assert_that(found).is_empty()


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

    def test_custom_entry_is_sized_by_allocation(self, tmp_path: Path):
        redist = tmp_path / "CustomGames" / "MyGame" / "_CommonRedist"
        redist.mkdir(parents=True)
        installer = redist / "setup.exe"
        installer.write_bytes(b"\x00" * 100_000)
        platform = FakePlatformAdapter(home_dir=tmp_path)
        platform.set_allocated_bytes(installer, 8192)

        result = ScanEngine(platform, ExclusionRegistry()).scan(custom_paths=[tmp_path / "CustomGames"])

        custom_sizes = {entry.path: entry.size_bytes for entry in result.entries if entry.client_name == "Custom"}
        assert_that(custom_sizes).is_equal_to({installer: 8192})

    def test_custom_entry_that_frees_nothing_is_dropped(self, tmp_path: Path):
        redist = tmp_path / "CustomGames" / "MyGame" / "_CommonRedist"
        redist.mkdir(parents=True)
        installer = redist / "setup.exe"
        installer.write_bytes(b"\x00" * 512)
        os.link(installer, tmp_path / "kept_elsewhere.exe")
        kept = redist / "vc_redist.exe"
        kept.write_bytes(b"\x00" * 64)

        engine = ScanEngine(FakePlatformAdapter(home_dir=tmp_path), ExclusionRegistry())
        result = engine.scan(custom_paths=[tmp_path / "CustomGames"])

        custom_paths = [entry.path for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_paths).is_equal_to([kept])

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

    def test_custom_path_cancel_after_first_entry_skips_rest(self, tmp_path: Path):
        custom = tmp_path / "Library"
        for game_name in ("GameA", "GameB"):
            redist = custom / game_name / "_CommonRedist"
            redist.mkdir(parents=True)
            (redist / "setup.exe").write_bytes(b"\x00" * 256)
            (redist / "vcredist.exe").write_bytes(b"\x00" * 256)

        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        cancel = threading.Event()
        result = engine.scan(on_found=lambda entry: cancel.set(), custom_paths=[custom], cancel=cancel)
        custom_entries = [entry for entry in result.entries if entry.client_name == "Custom"]
        assert_that(custom_entries).is_length(1)

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


class TestScanEngineChecksAnEntryAgain:
    @staticmethod
    def _make_library_with_a_leftover(tmp_path: Path) -> tuple[ScanEngine, JunkEntry]:
        library = tmp_path / "Steam"
        for directory_name in ("Installed Game", "Old Game"):
            game_dir = library / "steamapps" / "common" / directory_name
            game_dir.mkdir(parents=True)
            (game_dir / "data.bin").write_bytes(b"\x00" * 3000)
        write_app_manifest(library, 10, "Installed Game")
        engine = ScanEngine(FakePlatformAdapter(install_path=library, home_dir=tmp_path), ExclusionRegistry())
        (leftover,) = (entry for entry in engine.scan().entries if entry.category is JunkCategory.LEFTOVER)
        return engine, leftover

    def test_entry_stands_while_its_client_would_still_offer_it(self, tmp_path: Path):
        engine, leftover = self._make_library_with_a_leftover(tmp_path)

        assert_that(engine.still_offers(leftover)).is_true()

    def test_entry_falls_once_its_client_would_not_offer_it(self, tmp_path: Path):
        engine, leftover = self._make_library_with_a_leftover(tmp_path)

        write_app_manifest(tmp_path / "Steam", 20, "Old Game")

        assert_that(engine.still_offers(leftover)).is_false()

    @pytest.mark.parametrize("client_name", ["Custom", "Epic Games"], ids=["no-client", "another-client"])
    def test_entry_is_put_only_to_the_client_it_came_from(self, tmp_path: Path, client_name: str):
        engine, leftover = self._make_library_with_a_leftover(tmp_path)

        write_app_manifest(tmp_path / "Steam", 20, "Old Game")

        assert_that(engine.still_offers(replace(leftover, client_name=client_name))).is_true()
