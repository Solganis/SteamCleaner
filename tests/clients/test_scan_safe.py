import os
from typing import TYPE_CHECKING

from assertpy2 import assert_that
from helpers import FakePlatformAdapter, ListedEntriesClient

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _entry(path: Path, claimed_size: int) -> JunkEntry:
    return JunkEntry(
        path=path,
        category=JunkCategory.REDISTRIBUTABLE,
        size_bytes=claimed_size,
        client_name="Listed entries",
    )


class TestScanSafeSizes:
    def test_entry_is_sized_by_everything_its_directory_holds(self, tmp_path: Path):
        redist = tmp_path / "Game" / "_CommonRedist"
        redist.mkdir(parents=True)
        (redist / "setup.exe").write_bytes(b"\x00" * 1000)
        (redist / "readme.txt").write_bytes(b"\x00" * 24)
        client = ListedEntriesClient(FakePlatformAdapter(), ExclusionRegistry(), [_entry(redist, 1000)])
        assert_that([entry.size_bytes for entry in client.scan_safe()]).is_equal_to([1024])

    def test_entry_is_sized_by_allocation_not_by_file_length(self, tmp_path: Path):
        dump = tmp_path / "crash.dmp"
        dump.write_bytes(b"\x00" * 100_000)
        platform = FakePlatformAdapter()
        platform.set_allocated_bytes(dump, 8192)
        client = ListedEntriesClient(platform, ExclusionRegistry(), [_entry(dump, 100_000)])
        assert_that(list(client.scan_safe())).is_equal_to([_entry(dump, 8192)])

    def test_entry_that_frees_nothing_is_dropped(self, tmp_path: Path):
        dump = tmp_path / "crash.dmp"
        dump.write_bytes(b"\x00" * 500)
        os.link(dump, tmp_path / "kept_elsewhere.dmp")
        other = tmp_path / "other.dmp"
        other.write_bytes(b"\x00" * 40)
        client = ListedEntriesClient(FakePlatformAdapter(), ExclusionRegistry(), [_entry(dump, 500), _entry(other, 40)])
        assert_that(list(client.scan_safe())).is_equal_to([_entry(other, 40)])

    def test_entry_of_a_single_byte_is_kept(self, tmp_path: Path):
        dump = tmp_path / "crash.dmp"
        dump.write_bytes(b"\x00")
        client = ListedEntriesClient(FakePlatformAdapter(), ExclusionRegistry(), [_entry(dump, 1)])
        assert_that(list(client.scan_safe())).is_equal_to([_entry(dump, 1)])

    def test_excluded_entry_is_not_yielded(self, tmp_path: Path):
        shared = tmp_path / "Steamworks Shared" / "_CommonRedist"
        shared.mkdir(parents=True)
        (shared / "setup.exe").write_bytes(b"\x00" * 1000)
        client = ListedEntriesClient(FakePlatformAdapter(), ExclusionRegistry(), [_entry(shared, 1000)])
        assert_that(list(client.scan_safe())).is_empty()

    def test_entry_after_an_excluded_one_is_still_yielded(self, tmp_path: Path):
        shared = tmp_path / "Steamworks Shared" / "_CommonRedist"
        shared.mkdir(parents=True)
        (shared / "setup.exe").write_bytes(b"\x00" * 1000)
        dump = tmp_path / "crash.dmp"
        dump.write_bytes(b"\x00" * 40)
        entries = [_entry(shared, 1000), _entry(dump, 40)]
        client = ListedEntriesClient(FakePlatformAdapter(), ExclusionRegistry(), entries)
        assert_that(list(client.scan_safe())).is_equal_to([_entry(dump, 40)])
