from __future__ import annotations

from pathlib import Path

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult


def _make_entry(path: Path, size: int = 1024) -> JunkEntry:
    return JunkEntry(
        path=path,
        category=JunkCategory.REDISTRIBUTABLE,
        size_bytes=size,
        client_name="Steam",
    )


class TestCleanEngineDryRun:
    def test_dry_run_no_deletion(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 1024)

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(dry_run=True)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert stats.bytes_freed == 1024
        assert target.exists()

    def test_dry_run_callback(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        callbacks: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(dry_run=True)
        engine.clean(result, callback=lambda e, ok: callbacks.append((e, ok)))

        assert len(callbacks) == 1
        assert callbacks[0][1] is True


class TestCleanEngineReal:
    def test_delete_directory(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 1024)

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert not target.exists()

    def test_delete_file(self, tmp_path: Path):
        target = tmp_path / "crash.dmp"
        target.write_bytes(b"\x00" * 512)

        result = ScanResult(entries=[_make_entry(target, size=512)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert not target.exists()

    def test_skip_nonexistent(self, tmp_path: Path):
        target = tmp_path / "gone"
        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 0
        assert stats.skipped == 1

    def test_skip_symlink(self, tmp_path: Path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)

        result = ScanResult(entries=[_make_entry(link)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.skipped == 1
        assert "symlink" in stats.errors[0].lower() or "junction" in stats.errors[0].lower()
        assert real.exists()


class TestCleanEngineMultiple:
    def test_mixed_results(self, tmp_path: Path):
        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "f.exe").write_bytes(b"\x00" * 100)
        missing = tmp_path / "missing"

        result = ScanResult(entries=[_make_entry(existing, 100), _make_entry(missing, 200)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert stats.skipped == 1
        assert stats.bytes_freed == 100
