from __future__ import annotations

from pathlib import Path

from steamcleaner.utils.fs import format_size, is_reparse_point, safe_rmtree


class TestFormatSize:
    def test_bytes(self):
        assert format_size(512) == "512 B"

    def test_kilobytes(self):
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024 * 10) == "10.0 MB"

    def test_gigabytes(self):
        assert format_size(1024 * 1024 * 1024 * 3) == "3.0 GB"

    def test_zero(self):
        assert format_size(0) == "0 B"


class TestIsReparsePoint:
    def test_regular_dir(self, tmp_path: Path):
        d = tmp_path / "normal"
        d.mkdir()
        assert not is_reparse_point(d)

    def test_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        assert is_reparse_point(link)

    def test_nonexistent(self, tmp_path: Path):
        assert not is_reparse_point(tmp_path / "nope")


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
