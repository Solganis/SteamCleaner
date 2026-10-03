import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self
from unittest.mock import patch

import pytest
from assertpy2 import assert_that

from steamcleaner.utils.fs import dir_size, format_size, is_reparse_point, list_subdirs, safe_rmtree, walk_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


class _InaccessibleDirEntry:
    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        raise PermissionError(f"Access is denied: {self.path}")


class _AliasDirEntry:
    """A file as Windows lists an app execution alias: regular, not a symlink, carrying the reparse flag."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return True

    def is_symlink(self) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool = True) -> SimpleNamespace:
        return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT, st_size=7)


class _JunctionDirEntry:
    """A directory as Windows lists a junction: a directory carrying the reparse flag."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return True

    def stat(self, *, follow_symlinks: bool = True) -> SimpleNamespace:
        attributes = stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT
        return SimpleNamespace(st_file_attributes=attributes)


class _UnreadableAttributesDirEntry:
    """A directory that lists as one but whose attributes cannot be read."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return True

    def stat(self, *, follow_symlinks: bool = True) -> SimpleNamespace:
        raise PermissionError(f"Access is denied: {self.path}")


def _scandir_with(directory: Path, extra_entry: object) -> _FakeScandirIterator:
    with os.scandir(directory) as scanner:
        return _FakeScandirIterator([extra_entry, *scanner])


class _FakeScandirIterator:
    def __init__(self, entries: Iterable[object]) -> None:
        self._entries = list(entries)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def __iter__(self) -> Iterator[object]:
        return iter(self._entries)


def _scandir_with_inaccessible_entry(directory: Path) -> _FakeScandirIterator:
    with os.scandir(directory) as scanner:
        return _FakeScandirIterator([_InaccessibleDirEntry(directory / "locked"), *scanner])


class TestFormatSize:
    def test_bytes(self):
        assert_that(format_size(512)).is_equal_to("512 B")

    def test_kilobytes(self):
        assert_that(format_size(1536)).is_equal_to("1.5 KB")

    def test_megabytes(self):
        assert_that(format_size(1024 * 1024 * 10)).is_equal_to("10.0 MB")

    def test_gigabytes(self):
        assert_that(format_size(1024 * 1024 * 1024 * 3)).is_equal_to("3.0 GB")

    def test_terabytes(self):
        assert_that(format_size(1024 * 1024 * 1024 * 1024 * 2)).is_equal_to("2.0 TB")

    def test_zero(self):
        assert_that(format_size(0)).is_equal_to("0 B")


class TestIsReparsePoint:
    def test_regular_dir(self, tmp_path: Path):
        normal_dir = tmp_path / "normal"
        normal_dir.mkdir()
        assert_that(is_reparse_point(normal_dir)).is_false()

    def test_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert_that(is_reparse_point(link)).is_true()

    def test_nonexistent(self, tmp_path: Path):
        assert_that(is_reparse_point(tmp_path / "nope")).is_false()

    def test_windows_reparse_attribute(self, tmp_path: Path):
        # lstat() has no st_file_attributes off Windows, so it is mocked to run the check on every OS.
        target = tmp_path / "item"
        target.mkdir()
        fake_stat = SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with patch.object(Path, "lstat", return_value=fake_stat):
            assert_that(is_reparse_point(target)).is_true()

    def test_windows_attributes_without_the_reparse_flag(self, tmp_path: Path):
        other_attributes = stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_COMPRESSED
        fake_stat = SimpleNamespace(st_file_attributes=other_attributes, st_mode=stat.S_IFLNK | 0o777)
        with patch.object(Path, "lstat", return_value=fake_stat):
            assert_that(is_reparse_point(tmp_path)).is_false()

    @pytest.mark.parametrize(("mode", "is_link"), [(stat.S_IFLNK | 0o777, True), (stat.S_IFDIR | 0o755, False)])
    def test_stat_without_windows_attributes_is_judged_by_its_mode(self, tmp_path: Path, mode: int, is_link: bool):
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=mode)):
            assert_that(is_reparse_point(tmp_path)).is_equal_to(is_link)


class TestWalkFiles:
    def test_yields_files_with_sizes(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_bytes(b"\x00" * 200)
        results = list(walk_files(tmp_path))
        sizes = {path.name: size for path, size in results}
        assert_that(sizes["a.txt"]).is_equal_to(100)
        assert_that(sizes["b.txt"]).is_equal_to(200)

    def test_skips_symlinks(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_bytes(b"data")
        symdir = tmp_path / "symdir"
        symdir.symlink_to(real)
        results = list(walk_files(tmp_path))
        result_names = [path.parent.name for path, _ in results]
        assert_that(result_names).does_not_contain("symdir")
        assert_that(results).is_length(1)

    @pytest.mark.parametrize("entry_type", [_JunctionDirEntry, _UnreadableAttributesDirEntry])
    def test_does_not_enter_a_subdir_that_is_a_reparse_point_or_cannot_be_told(self, tmp_path: Path, entry_type: type):
        (tmp_path / "kept.bin").write_bytes(b"\x00" * 100)
        elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
        elsewhere.mkdir()
        (elsewhere / "file.txt").write_bytes(b"data")
        scanner = _scandir_with(tmp_path, entry_type(elsewhere))
        with patch.object(os, "scandir", return_value=scanner):
            results = list(walk_files(tmp_path))
        assert_that(results).is_equal_to([(tmp_path / "kept.bin", 100)])

    def test_nonexistent_dir(self, tmp_path: Path):
        results = list(walk_files(tmp_path / "nope"))
        assert_that(results).is_equal_to([])

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        results = list(walk_files(empty))
        assert_that(results).is_equal_to([])

    def test_skips_entry_raising_os_error(self, tmp_path: Path):
        (tmp_path / "kept.bin").write_bytes(b"\x00" * 100)
        scanner = _scandir_with_inaccessible_entry(tmp_path)
        with patch.object(os, "scandir", return_value=scanner):
            results = list(walk_files(tmp_path))
        assert_that(results).is_equal_to([(tmp_path / "kept.bin", 100)])

    def test_skips_a_file_that_is_a_reparse_point_without_being_a_symlink(self, tmp_path: Path):
        (tmp_path / "kept.bin").write_bytes(b"\x00" * 100)
        with os.scandir(tmp_path) as real_entries:
            scanner = _FakeScandirIterator([_AliasDirEntry(tmp_path / "alias.exe"), *real_entries])
        with patch.object(os, "scandir", return_value=scanner):
            results = list(walk_files(tmp_path))
        assert_that(results).is_equal_to([(tmp_path / "kept.bin", 100)])


class TestDirSize:
    def test_calculates_total(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 100)
        (tmp_path / "b.txt").write_bytes(b"\x00" * 200)
        assert_that(dir_size(tmp_path)).is_equal_to(300)

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert_that(dir_size(empty)).is_equal_to(0)

    def test_nested_files(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.bin").write_bytes(b"\x00" * 500)
        assert_that(dir_size(tmp_path)).is_equal_to(500)


class TestListSubdirs:
    def test_returns_subdirs(self, tmp_path: Path):
        (tmp_path / "dir_a").mkdir()
        (tmp_path / "dir_b").mkdir()
        (tmp_path / "file.txt").write_bytes(b"data")
        result = list_subdirs(tmp_path)
        names = {path.name for path in result}
        assert_that(names).is_equal_to({"dir_a", "dir_b"})

    def test_skips_symlinks(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        result = list_subdirs(tmp_path)
        names = {path.name for path in result}
        assert_that(names).does_not_contain("link")

    def test_nonexistent_dir(self, tmp_path: Path):
        assert_that(list_subdirs(tmp_path / "nope")).is_equal_to([])

    @pytest.mark.parametrize("entry_type", [_JunctionDirEntry, _UnreadableAttributesDirEntry])
    def test_skips_a_subdir_that_is_a_reparse_point_or_cannot_be_told(self, tmp_path: Path, entry_type: type):
        (tmp_path / "real").mkdir()
        scanner = _scandir_with(tmp_path, entry_type(tmp_path / "junction"))
        with patch.object(os, "scandir", return_value=scanner):
            result = list_subdirs(tmp_path)
        assert_that(result).is_equal_to([tmp_path / "real"])

    @pytest.mark.skipif(sys.platform != "win32", reason="junctions are an NTFS reparse point")
    def test_skips_a_real_junction(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_bytes(b"data")
        junction = tmp_path / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(real)], check=True, capture_output=True)

        assert_that(list_subdirs(tmp_path)).is_equal_to([real])
        assert_that(list(walk_files(tmp_path))).is_equal_to([(real / "file.txt", 4)])

    def test_skips_entry_raising_os_error(self, tmp_path: Path):
        (tmp_path / "visible").mkdir()
        scanner = _scandir_with_inaccessible_entry(tmp_path)
        with patch.object(os, "scandir", return_value=scanner):
            result = list_subdirs(tmp_path)
        assert_that(result).is_equal_to([tmp_path / "visible"])


class TestSafeRmtree:
    def test_removes_dir(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "file.txt").write_bytes(b"data")
        assert_that(safe_rmtree(target)).is_true()
        assert_that(str(target)).does_not_exist()

    def test_refuses_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert_that(safe_rmtree(link)).is_false()
        assert_that(str(real)).exists()
