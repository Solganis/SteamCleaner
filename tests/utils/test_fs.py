from pathlib import Path
from unittest.mock import patch

from assertpy2 import assert_that

from steamcleaner.utils.fs import dir_size, format_size, is_reparse_point, list_subdirs, safe_rmtree, walk_files


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

    def test_skips_reparse_point_subdir(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_bytes(b"data")
        reparse = tmp_path / "junction"
        reparse.mkdir()
        with patch("steamcleaner.utils.fs.is_reparse_point", side_effect=lambda path: path == reparse):
            results = list(walk_files(tmp_path))
        result_paths = [path for path, _ in results]
        assert_that(any(path.name == "file.txt" for path in result_paths)).is_true()
        assert_that(any("junction" in str(path) for path in result_paths)).is_false()

    def test_nonexistent_dir(self, tmp_path: Path):
        results = list(walk_files(tmp_path / "nope"))
        assert_that(results).is_equal_to([])

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        results = list(walk_files(empty))
        assert_that(results).is_equal_to([])


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
