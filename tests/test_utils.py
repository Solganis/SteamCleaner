from pathlib import Path
from unittest.mock import patch

from steamcleaner.utils.fs import dir_size, format_size, is_reparse_point, list_subdirs, safe_rmtree, walk_files


class TestFormatSize:
    def test_bytes(self):
        assert format_size(512) == "512 B"

    def test_kilobytes(self):
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024 * 10) == "10.0 MB"

    def test_gigabytes(self):
        assert format_size(1024 * 1024 * 1024 * 3) == "3.0 GB"

    def test_terabytes(self):
        assert format_size(1024 * 1024 * 1024 * 1024 * 2) == "2.0 TB"

    def test_zero(self):
        assert format_size(0) == "0 B"


class TestIsReparsePoint:
    def test_regular_dir(self, tmp_path: Path):
        normal_dir = tmp_path / "normal"
        normal_dir.mkdir()
        assert not is_reparse_point(normal_dir)

    def test_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert is_reparse_point(link)

    def test_nonexistent(self, tmp_path: Path):
        assert not is_reparse_point(tmp_path / "nope")


class TestWalkFiles:
    def test_yields_files_with_sizes(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 100)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_bytes(b"\x00" * 200)
        results = list(walk_files(tmp_path))
        sizes = {path.name: size for path, size in results}
        assert sizes["a.txt"] == 100
        assert sizes["b.txt"] == 200

    def test_skips_symlinks(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_bytes(b"data")
        symdir = tmp_path / "symdir"
        symdir.symlink_to(real)
        results = list(walk_files(tmp_path))
        result_names = [path.parent.name for path, _ in results]
        assert "symdir" not in result_names
        assert len(results) == 1

    def test_skips_reparse_point_subdir(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        (real / "file.txt").write_bytes(b"data")
        reparse = tmp_path / "junction"
        reparse.mkdir()
        with patch("steamcleaner.utils.fs.is_reparse_point", side_effect=lambda path: path == reparse):
            results = list(walk_files(tmp_path))
        result_paths = [path for path, _ in results]
        assert any(path.name == "file.txt" for path in result_paths)
        assert not any("junction" in str(path) for path in result_paths)

    def test_nonexistent_dir(self, tmp_path: Path):
        results = list(walk_files(tmp_path / "nope"))
        assert results == []

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        results = list(walk_files(empty))
        assert results == []


class TestDirSize:
    def test_calculates_total(self, tmp_path: Path):
        (tmp_path / "a.txt").write_bytes(b"\x00" * 100)
        (tmp_path / "b.txt").write_bytes(b"\x00" * 200)
        assert dir_size(tmp_path) == 300

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert dir_size(empty) == 0

    def test_nested_files(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.bin").write_bytes(b"\x00" * 500)
        assert dir_size(tmp_path) == 500


class TestListSubdirs:
    def test_returns_subdirs(self, tmp_path: Path):
        (tmp_path / "dir_a").mkdir()
        (tmp_path / "dir_b").mkdir()
        (tmp_path / "file.txt").write_bytes(b"data")
        result = list_subdirs(tmp_path)
        names = {path.name for path in result}
        assert names == {"dir_a", "dir_b"}

    def test_skips_symlinks(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        result = list_subdirs(tmp_path)
        names = {path.name for path in result}
        assert "link" not in names

    def test_nonexistent_dir(self, tmp_path: Path):
        assert list_subdirs(tmp_path / "nope") == []


class TestSafeRmtree:
    def test_removes_dir(self, tmp_path: Path):
        target = tmp_path / "target"
        target.mkdir()
        (target / "file.txt").write_bytes(b"data")
        assert safe_rmtree(target)
        assert not target.exists()

    def test_refuses_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert not safe_rmtree(link)
        assert real.exists()
