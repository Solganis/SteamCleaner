import itertools
import logging
import os
from typing import TYPE_CHECKING

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.utils.fs import disk_usage

if TYPE_CHECKING:
    from pathlib import Path

    from steamcleaner.platform.base import FileAllocation


class _PartlyUnreadableAdapter(FakePlatformAdapter):
    def __init__(self, unreadable: Path) -> None:
        super().__init__()
        self._unreadable = unreadable

    def file_allocation(self, path: Path) -> FileAllocation:
        if path == self._unreadable:
            raise PermissionError(f"Access is denied: {path}")
        return super().file_allocation(path)


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


class TestDiskUsage:
    def test_single_file_counts_its_allocation(self, tmp_path: Path):
        dump = _write(tmp_path / "crash.dmp", 1000)
        assert_that(disk_usage(dump, FakePlatformAdapter())).is_equal_to(1000)

    def test_directory_sums_every_file_below_it(self, tmp_path: Path):
        redist = tmp_path / "_CommonRedist"
        _write(redist / "setup.exe", 1000)
        _write(redist / "vcredist" / "2019" / "vc_redist.x64.exe", 300)
        _write(redist / "readme.txt", 20)
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(1320)

    def test_allocation_wins_over_file_length(self, tmp_path: Path):
        cache = tmp_path / "shadercache"
        compressed = _write(cache / "compressed.bin", 100_000)
        tiny = _write(cache / "tiny.bin", 10)
        platform = FakePlatformAdapter()
        platform.set_allocated_bytes(compressed, 8192)
        platform.set_allocated_bytes(tiny, 4096)
        assert_that(disk_usage(cache, platform)).is_equal_to(12_288)

    def test_hard_links_inside_the_tree_count_once(self, tmp_path: Path):
        redist = tmp_path / "redist"
        original = _write(redist / "setup.exe", 500)
        os.link(original, redist / "setup_copy.exe")
        _write(redist / "other.exe", 40)
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(540)

    def test_file_with_a_name_outside_the_tree_frees_nothing(self, tmp_path: Path):
        redist = tmp_path / "redist"
        original = _write(redist / "setup.exe", 500)
        os.link(original, tmp_path / "kept_elsewhere.exe")
        _write(redist / "other.exe", 40)
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(40)

    def test_single_file_with_another_name_frees_nothing(self, tmp_path: Path):
        dump = _write(tmp_path / "crash.dmp", 500)
        os.link(dump, tmp_path / "crash_copy.dmp")
        assert_that(disk_usage(dump, FakePlatformAdapter())).is_equal_to(0)

    def test_three_names_inside_the_tree_count_once(self, tmp_path: Path):
        redist = tmp_path / "redist"
        original = _write(redist / "b_setup.exe", 500)
        os.link(original, redist / "a_first_copy.exe")
        (redist / "nested").mkdir()
        os.link(original, redist / "nested" / "c_second_copy.exe")
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(500)

    def test_two_of_three_names_inside_the_tree_free_nothing(self, tmp_path: Path):
        redist = tmp_path / "redist"
        original = _write(redist / "b_setup.exe", 500)
        os.link(original, redist / "a_first_copy.exe")
        os.link(original, tmp_path / "kept_elsewhere.exe")
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(0)

    @pytest.mark.parametrize("walk_order", list(itertools.permutations(range(3))))
    def test_walk_order_does_not_change_what_three_names_count_for(self, tmp_path: Path, monkeypatch, walk_order):
        redist = tmp_path / "redist"
        names = [_write(redist / "setup.exe", 500), redist / "first_copy.exe", redist / "second_copy.exe"]
        os.link(names[0], names[1])
        os.link(names[0], names[2])
        monkeypatch.setattr(
            "steamcleaner.utils.fs.walk_files", lambda _root: iter([(names[index], 500) for index in walk_order])
        )
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(500)

    @pytest.mark.parametrize("walk_order", list(itertools.permutations(range(2))))
    def test_walk_order_does_not_free_a_file_with_a_name_outside(self, tmp_path: Path, monkeypatch, walk_order):
        redist = tmp_path / "redist"
        names = [_write(redist / "setup.exe", 500), redist / "first_copy.exe"]
        os.link(names[0], names[1])
        os.link(names[0], tmp_path / "kept_elsewhere.exe")
        monkeypatch.setattr(
            "steamcleaner.utils.fs.walk_files", lambda _root: iter([(names[index], 500) for index in walk_order])
        )
        assert_that(disk_usage(redist, FakePlatformAdapter())).is_equal_to(0)

    def test_symlinked_directory_holds_nothing(self, tmp_path: Path):
        real = tmp_path / "real"
        _write(real / "setup.exe", 500)
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        assert_that(disk_usage(link, FakePlatformAdapter())).is_equal_to(0)

    def test_missing_path_holds_nothing(self, tmp_path: Path):
        assert_that(disk_usage(tmp_path / "gone", FakePlatformAdapter())).is_equal_to(0)

    def test_file_that_cannot_be_measured_is_left_out(self, tmp_path: Path, caplog):
        redist = tmp_path / "redist"
        locked = _write(redist / "locked.exe", 500)
        _write(redist / "other.exe", 40)
        with caplog.at_level(logging.DEBUG, logger="steamcleaner.utils.fs"):
            usage = disk_usage(redist, _PartlyUnreadableAdapter(locked))
        assert_that(usage).is_equal_to(40)
        assert_that([record.getMessage() for record in caplog.records]).is_equal_to(
            [f"Cannot measure {locked}: Access is denied: {locked}"]
        )
