import threading
from pathlib import Path

from helpers import FakePlatformAdapter

from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry


def _make_steam_with_games(tmp_path: Path, game_count: int) -> FakePlatformAdapter:
    steam = tmp_path / ".local" / "share" / "Steam"
    common = steam / "steamapps" / "common"
    common.mkdir(parents=True)
    for i in range(game_count):
        game = common / f"Game{i}"
        redist = game / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "setup.exe").write_bytes(b"\x00" * 1024)
    shader = steam / "steamapps" / "shadercache" / "123"
    shader.mkdir(parents=True)
    (shader / "cache.bin").write_bytes(b"\x00" * 1024)
    logs = steam / "logs"
    logs.mkdir()
    (logs / "steam.log").write_bytes(b"\x00" * (1024 * 1024 + 1))
    dumps = steam / "dumps"
    dumps.mkdir()
    (dumps / "crash.dmp").write_bytes(b"\x00" * 512)
    return FakePlatformAdapter(home_dir=tmp_path)


class TestCancelBeforeScan:
    def test_cancel_already_set_returns_empty(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 3)
        engine = ScanEngine(platform, ExclusionRegistry())
        cancel = threading.Event()
        cancel.set()
        result = engine.scan(cancel=cancel)
        assert len(result.entries) == 0


class TestCancelMidScan:
    def test_cancel_stops_between_games(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 10)
        client = SteamClient(platform, ExclusionRegistry())
        cancel = threading.Event()
        entries = []
        for entry in client.scan_safe(cancel=cancel):
            entries.append(entry)
            if len(entries) >= 2:
                cancel.set()
        assert len(entries) < 10

    def test_cancel_stops_scan_junk_between_phases(self, tmp_path: Path):
        """Cancel after redist scan should skip shader cache, logs, dumps."""
        platform = _make_steam_with_games(tmp_path, 1)
        client = SteamClient(platform, ExclusionRegistry())
        cancel = threading.Event()
        entries = []
        for entry in client.scan_safe(cancel=cancel):
            entries.append(entry)
            if entry.category == JunkCategory.REDISTRIBUTABLE:
                cancel.set()
        categories = {entry.category for entry in entries}
        assert JunkCategory.REDISTRIBUTABLE in categories
        assert JunkCategory.SHADER_CACHE not in categories
        assert JunkCategory.OLD_LOG not in categories

    def test_partial_results_returned_via_engine(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 5)
        cancel = threading.Event()

        engine = ScanEngine(platform, ExclusionRegistry())
        result_holder: list = []

        def run_scan():
            result_holder.append(engine.scan(cancel=cancel))

        thread = threading.Thread(target=run_scan)
        thread.start()
        threading.Event().wait(0.05)
        cancel.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(result_holder) == 1
        assert len(result_holder[0].entries) < 10


class TestCancelClientProperty:
    def test_cancelled_false_by_default(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert not client.cancelled

    def test_cancelled_true_after_set(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        client._cancel = threading.Event()
        assert client._cancel is not None
        client._cancel.set()
        assert client.cancelled

    def test_cancel_reset_after_scan_safe(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 1)
        client = SteamClient(platform, ExclusionRegistry())
        cancel = threading.Event()
        for _ in client.scan_safe(cancel=cancel):
            pass
        assert client._cancel is None
