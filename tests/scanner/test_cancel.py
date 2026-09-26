import threading
from typing import TYPE_CHECKING

from assertpy2 import assert_that
from helpers import FakePlatformAdapter, scan_cancelling_after, scan_with_cancel_already_set

from steamcleaner.clients.base import GameClient
from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from steamcleaner.platform.base import PlatformAdapter


class _CancelUnawareClient(GameClient):
    def __init__(self, platform: PlatformAdapter, exclusions: ExclusionRegistry, entries: list[JunkEntry]) -> None:
        super().__init__(platform, exclusions)
        self._entries = entries

    @property
    def name(self) -> str:
        return "Cancel-unaware"

    def is_installed(self) -> bool:
        return True

    def scan_junk(self) -> Iterator[JunkEntry]:
        yield from self._entries


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
        assert_that(result.entries).is_length(0)

    def test_cancel_already_set_skips_steam_libraries(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 3)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(scan_with_cancel_already_set(client)).is_empty()


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
        assert_that(len(entries)).is_less_than(10)

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
        assert_that(categories).contains(JunkCategory.REDISTRIBUTABLE)
        assert_that(categories).does_not_contain(JunkCategory.SHADER_CACHE)
        assert_that(categories).does_not_contain(JunkCategory.OLD_LOG)

    def test_cancel_during_shader_cache_skips_remaining_caches_and_dumps(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 1)
        second_shader = tmp_path / ".local" / "share" / "Steam" / "steamapps" / "shadercache" / "456"
        second_shader.mkdir()
        (second_shader / "cache.bin").write_bytes(b"\x00" * 1024)
        client = SteamClient(platform, ExclusionRegistry())
        entries = scan_cancelling_after(client, lambda entry: entry.category == JunkCategory.SHADER_CACHE)
        categories = [entry.category for entry in entries]
        assert_that(categories.count(JunkCategory.SHADER_CACHE)).is_equal_to(1)
        assert_that(categories).does_not_contain(JunkCategory.CRASH_DUMP)

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
        assert_that(thread.is_alive()).is_false()
        assert_that(result_holder).is_length(1)
        assert_that(len(result_holder[0].entries)).is_less_than(10)


class TestCancelClientProperty:
    def test_cancelled_false_by_default(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        assert_that(client.cancelled).is_false()

    def test_cancelled_true_after_set(self, tmp_path: Path):
        platform = FakePlatformAdapter(home_dir=tmp_path)
        client = SteamClient(platform, ExclusionRegistry())
        client._cancel = threading.Event()
        assert isinstance(client._cancel, threading.Event)
        client._cancel.set()
        assert_that(client.cancelled).is_true()

    def test_cancel_reset_after_scan_safe(self, tmp_path: Path):
        platform = _make_steam_with_games(tmp_path, 1)
        client = SteamClient(platform, ExclusionRegistry())
        cancel = threading.Event()
        for _ in client.scan_safe(cancel=cancel):
            pass
        assert_that(client._cancel).is_none()

    def test_scan_safe_stops_client_that_ignores_cancel(self, tmp_path: Path):
        entries = [
            JunkEntry(
                path=tmp_path / f"redist_{index}",
                category=JunkCategory.REDISTRIBUTABLE,
                size_bytes=1024,
                client_name="Cancel-unaware",
            )
            for index in range(3)
        ]
        client = _CancelUnawareClient(FakePlatformAdapter(home_dir=tmp_path), ExclusionRegistry(), entries)
        collected = scan_cancelling_after(client, lambda entry: entry == entries[0])
        assert_that(collected).is_equal_to(entries[:1])
