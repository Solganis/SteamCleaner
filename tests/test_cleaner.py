from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult


def _make_entry(path: Path, size: int = 1024, category: JunkCategory = JunkCategory.REDISTRIBUTABLE) -> JunkEntry:
    return JunkEntry(
        path=path,
        category=category,
        size_bytes=size,
        client_name="Steam",
    )


class TestCleanEngineDryRun:
    def test_dry_run_preserves_files(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 1024)

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(dry_run=True)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert stats.bytes_freed == 1024
        assert target.exists()
        assert (target / "file.exe").exists()

    def test_dry_run_reports_all_entries(self, tmp_path: Path):
        entries = []
        for name in ("dir_a", "dir_b", "dir_c"):
            target = tmp_path / name
            target.mkdir()
            entries.append(_make_entry(target, size=500))

        result = ScanResult(entries=entries)
        engine = CleanEngine(dry_run=True)
        stats = engine.clean(result)

        assert stats.deleted == 3
        assert stats.bytes_freed == 1500
        assert all((tmp_path / name).exists() for name in ("dir_a", "dir_b", "dir_c"))

    def test_dry_run_callback_fires_for_each(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(dry_run=True)
        engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert len(callback_log) == 1
        assert callback_log[0][1] is True


class TestCleanEngineRealDeletion:
    def test_delete_directory_recursively(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 1024)
        (target / "nested").mkdir()
        (target / "nested" / "deep.dll").write_bytes(b"\x00" * 512)

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert not target.exists()

    def test_delete_single_file(self, tmp_path: Path):
        target = tmp_path / "crash.dmp"
        target.write_bytes(b"\x00" * 512)

        result = ScanResult(entries=[_make_entry(target, size=512, category=JunkCategory.CRASH_DUMP)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert not target.exists()

    def test_delete_does_not_affect_siblings(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "setup.exe").write_bytes(b"\x00" * 100)

        sibling = tmp_path / "game_data"
        sibling.mkdir()
        (sibling / "save.dat").write_bytes(b"\x00" * 200)

        result = ScanResult(entries=[_make_entry(target, size=100)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result)

        assert not target.exists()
        assert sibling.exists()
        assert (sibling / "save.dat").exists()

    def test_delete_only_specified_entries(self, tmp_path: Path):
        to_delete = tmp_path / "junk"
        to_delete.mkdir()
        (to_delete / "installer.exe").write_bytes(b"\x00" * 100)

        to_keep = tmp_path / "important"
        to_keep.mkdir()
        (to_keep / "data.bin").write_bytes(b"\x00" * 100)

        result = ScanResult(entries=[_make_entry(to_delete)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result)

        assert not to_delete.exists()
        assert to_keep.exists()
        assert (to_keep / "data.bin").exists()


class TestCleanEngineSafetyChecks:
    def test_skip_nonexistent_path(self, tmp_path: Path):
        target = tmp_path / "already_gone"
        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 0
        assert stats.skipped == 1

    def test_refuse_symlink_directory(self, tmp_path: Path):
        real_dir = tmp_path / "real_game_data"
        real_dir.mkdir()
        (real_dir / "important.dat").write_bytes(b"\x00" * 1024)

        symlink = tmp_path / "symlink_to_real"
        symlink.symlink_to(real_dir)

        result = ScanResult(entries=[_make_entry(symlink)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.skipped == 1
        assert len(stats.errors) == 1
        assert real_dir.exists()
        assert (real_dir / "important.dat").exists()

    def test_refuse_symlink_preserves_target_contents(self, tmp_path: Path):
        target_dir = tmp_path / "steam_library"
        target_dir.mkdir()
        game_save = target_dir / "savegame.dat"
        game_save.write_bytes(b"precious data")

        junction = tmp_path / "junction_link"
        junction.symlink_to(target_dir)

        result = ScanResult(entries=[_make_entry(junction)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result)

        assert target_dir.exists()
        assert game_save.read_bytes() == b"precious data"

    def test_error_during_deletion_is_captured(self, tmp_path: Path):
        target = tmp_path / "locked_dir"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)

        with patch.object(engine, "_delete", side_effect=PermissionError("Access denied")):
            stats = engine.clean(result)

        assert stats.deleted == 0
        assert stats.skipped == 1
        assert "Access denied" in stats.errors[0]
        assert target.exists()

    def test_error_callback_reports_failure(self, tmp_path: Path):
        target = tmp_path / "failing"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(use_trash=False, dry_run=False)

        with patch.object(engine, "_delete", side_effect=OSError("disk error")):
            engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert len(callback_log) == 1
        assert callback_log[0][1] is False

    def test_empty_scan_result_does_nothing(self):
        result = ScanResult(entries=[])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 0
        assert stats.skipped == 0
        assert stats.bytes_freed == 0
        assert stats.errors == []


class TestCleanEngineMultipleEntries:
    def test_mixed_existing_and_missing(self, tmp_path: Path):
        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "setup.exe").write_bytes(b"\x00" * 100)
        missing = tmp_path / "missing"

        result = ScanResult(entries=[_make_entry(existing, 100), _make_entry(missing, 200)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 1
        assert stats.skipped == 1
        assert stats.bytes_freed == 100

    def test_multiple_valid_deletions(self, tmp_path: Path):
        entries = []
        for name in ("cache_a", "cache_b", "cache_c"):
            target = tmp_path / name
            target.mkdir()
            (target / "data.bin").write_bytes(b"\x00" * 256)
            entries.append(_make_entry(target, size=256, category=JunkCategory.SHADER_CACHE))

        result = ScanResult(entries=entries)
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 3
        assert stats.bytes_freed == 768
        assert all(not (tmp_path / name).exists() for name in ("cache_a", "cache_b", "cache_c"))

    def test_partial_failure_continues(self, tmp_path: Path):
        good = tmp_path / "deletable"
        good.mkdir()
        (good / "junk.exe").write_bytes(b"\x00" * 100)

        bad = tmp_path / "undeletable"
        bad.mkdir()

        result = ScanResult(entries=[_make_entry(good, 100), _make_entry(bad, 200)])
        engine = CleanEngine(use_trash=False, dry_run=False)

        original_delete = engine._delete

        def selective_delete(path: Path):
            if path == bad:
                raise PermissionError("locked")
            original_delete(path)

        with patch.object(engine, "_delete", side_effect=selective_delete):
            stats = engine.clean(result)

        assert stats.deleted == 1
        assert stats.skipped == 1
        assert stats.bytes_freed == 100
        assert not good.exists()
        assert bad.exists()

    def test_bytes_freed_matches_deleted_entries(self, tmp_path: Path):
        small = tmp_path / "small.dmp"
        small.write_bytes(b"\x00" * 100)
        large = tmp_path / "large.dmp"
        large.write_bytes(b"\x00" * 5000)

        result = ScanResult(
            entries=[
                _make_entry(small, size=100, category=JunkCategory.CRASH_DUMP),
                _make_entry(large, size=5000, category=JunkCategory.CRASH_DUMP),
            ]
        )
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert stats.deleted == 2
        assert stats.bytes_freed == 5100


class TestCleanEngineTrashMode:
    def test_trash_mode_calls_send2trash(self, tmp_path: Path):
        target = tmp_path / "to_trash"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 100)

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=True, dry_run=False)

        with patch("steamcleaner.cleaner.engine.send2trash") as mock_trash:
            stats = engine.clean(result)

        mock_trash.assert_called_once_with(str(target))
        assert stats.deleted == 1

    def test_trash_error_is_captured(self, tmp_path: Path):
        target = tmp_path / "untrashable"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=True, dry_run=False)

        with patch("steamcleaner.cleaner.engine.send2trash", side_effect=OSError("trash full")):
            stats = engine.clean(result)

        assert stats.deleted == 0
        assert stats.skipped == 1
        assert "trash full" in stats.errors[0]
