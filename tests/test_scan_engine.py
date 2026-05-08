from __future__ import annotations

import threading
from pathlib import Path

from steamcleaner.models.junk import JunkEntry
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from tests.conftest import FakePlatformAdapter


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
        assert any("Scanning" in msg for msg in messages)

    def test_on_found_callback_called(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        found: list[JunkEntry] = []
        engine.scan(on_found=lambda entry: found.append(entry))
        assert len(found) > 0

    def test_progress_reports_not_installed(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg))
        assert any("not installed" in msg for msg in messages)

    def test_progress_reports_count(self, tmp_path: Path):
        platform = _make_steam_tree(tmp_path)
        engine = ScanEngine(platform, ExclusionRegistry())
        messages: list[str] = []
        engine.scan(progress=lambda msg, count: messages.append(msg))
        assert any("found" in msg for msg in messages)

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
        assert len(result.entries) < 10
