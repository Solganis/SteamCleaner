import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    import os


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

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(stats.bytes_trashed).is_equal_to(1024)
        assert_that(str(target)).exists()
        assert_that(str(target / "file.exe")).exists()

    def test_dry_run_reports_all_entries(self, tmp_path: Path):
        entries = []
        for name in ("dir_a", "dir_b", "dir_c"):
            target = tmp_path / name
            target.mkdir()
            entries.append(_make_entry(target, size=500))

        result = ScanResult(entries=entries)
        engine = CleanEngine(dry_run=True)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(3)
        assert_that(stats.bytes_trashed).is_equal_to(1500)
        assert_that(all((tmp_path / name).exists() for name in ("dir_a", "dir_b", "dir_c"))).is_true()

    def test_dry_run_callback_fires_for_each(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(dry_run=True)
        engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert_that(callback_log).is_length(1)
        assert_that(callback_log[0][1]).is_true()


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

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(str(target)).does_not_exist()

    def test_delete_single_file(self, tmp_path: Path):
        target = tmp_path / "crash.dmp"
        target.write_bytes(b"\x00" * 512)

        result = ScanResult(entries=[_make_entry(target, size=512, category=JunkCategory.CRASH_DUMP)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(str(target)).does_not_exist()

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

        assert_that(str(target)).does_not_exist()
        assert_that(str(sibling)).exists()
        assert_that(str(sibling / "save.dat")).exists()

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

        assert_that(str(to_delete)).does_not_exist()
        assert_that(str(to_keep)).exists()
        assert_that(str(to_keep / "data.bin")).exists()


class TestCleanEngineSafetyChecks:
    def test_skip_nonexistent_path(self, tmp_path: Path):
        target = tmp_path / "already_gone"
        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)

    def test_refuse_symlink_directory(self, tmp_path: Path):
        real_dir = tmp_path / "real_game_data"
        real_dir.mkdir()
        (real_dir / "important.dat").write_bytes(b"\x00" * 1024)

        symlink = tmp_path / "symlink_to_real"
        symlink.symlink_to(real_dir)

        result = ScanResult(entries=[_make_entry(symlink)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors).is_length(1)
        assert_that(str(real_dir)).exists()
        assert_that(str(real_dir / "important.dat")).exists()

    def test_refuse_symlink_callback_reports_failure(self, tmp_path: Path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        symlink = tmp_path / "link"
        symlink.symlink_to(real_dir)

        result = ScanResult(entries=[_make_entry(symlink)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert_that(callback_log).is_length(1)
        assert_that(callback_log[0][1]).is_false()

    def test_real_deletion_callback_reports_success(self, tmp_path: Path):
        target = tmp_path / "junk"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 100)

        result = ScanResult(entries=[_make_entry(target)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert_that(callback_log).is_length(1)
        assert_that(callback_log[0][1]).is_true()

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

        assert_that(str(target_dir)).exists()
        assert_that(game_save.read_bytes()).is_equal_to(b"precious data")

    def test_toctou_reparse_swap_after_gate_is_refused(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 100)

        result = ScanResult(entries=[_make_entry(target, size=100)])
        engine = CleanEngine(use_trash=False, dry_run=False)

        # First call is clean()'s gate (path still looks safe); second is _delete()'s re-check,
        # by which point the path was swapped for a junction. The engine must refuse and keep data.
        with patch("steamcleaner.cleaner.engine.is_reparse_point", side_effect=[False, True]):
            stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors).is_length(1)
        assert_that(stats.errors[0]).contains("reparse point")
        assert_that(str(target)).exists()
        assert_that(str(target / "file.exe")).exists()

    def test_error_during_deletion_is_captured(self, tmp_path: Path):
        target = tmp_path / "locked_dir"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=False, dry_run=False)

        with patch.object(engine, "_delete", side_effect=PermissionError("Access denied")):
            stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors[0]).contains("Access denied")
        assert_that(str(target)).exists()

    def test_error_callback_reports_failure(self, tmp_path: Path):
        target = tmp_path / "failing"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(use_trash=False, dry_run=False)

        with patch.object(engine, "_delete", side_effect=OSError("disk error")):
            engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert_that(callback_log).is_length(1)
        assert_that(callback_log[0][1]).is_false()

    def test_empty_scan_result_does_nothing(self):
        result = ScanResult(entries=[])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(0)
        assert_that(stats.bytes_freed).is_equal_to(0)
        assert_that(stats.errors).is_empty()


class TestCleanEngineExclusionGate:
    def test_refuse_builtin_excluded_path(self, tmp_path: Path):
        protected = tmp_path / "steamapps" / "common" / "Steamworks Shared" / "redist"
        protected.mkdir(parents=True)
        (protected / "shared.dll").write_bytes(b"\x00" * 128)

        result = ScanResult(entries=[_make_entry(protected, size=128)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors).is_length(1)
        assert_that(stats.errors[0]).contains("protected")
        assert_that(str(protected)).exists()
        assert_that(str(protected / "shared.dll")).exists()

    def test_excluded_path_is_refused_before_deletion_even_in_dry_run(self, tmp_path: Path):
        protected = tmp_path / "StarCraft" / "support"
        protected.mkdir(parents=True)

        result = ScanResult(entries=[_make_entry(protected)])
        engine = CleanEngine(use_trash=False, dry_run=True)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)

    def test_excluded_path_callback_reports_failure(self, tmp_path: Path):
        protected = tmp_path / "Heroes of the Storm" / "support"
        protected.mkdir(parents=True)

        result = ScanResult(entries=[_make_entry(protected)])
        callback_log: list[tuple[JunkEntry, bool]] = []
        engine = CleanEngine(use_trash=False, dry_run=False)
        engine.clean(result, callback=lambda entry, success: callback_log.append((entry, success)))

        assert_that(callback_log).is_length(1)
        assert_that(callback_log[0][1]).is_false()

    def test_user_added_exclusion_is_refused_at_delete_time(self, tmp_path: Path):
        protected = tmp_path / "MyMod" / "keepme"
        protected.mkdir(parents=True)
        (protected / "data.bin").write_bytes(b"\x00" * 64)

        registry = ExclusionRegistry()
        registry.add("keepme", "user-defined exclusion")
        result = ScanResult(entries=[_make_entry(protected, size=64)])
        engine = CleanEngine(use_trash=False, dry_run=False, exclusions=registry)
        stats = engine.clean(result)

        assert_that(stats.skipped).is_equal_to(1)
        assert_that(str(protected)).exists()

    def test_ordinary_junk_still_deletes_with_builtins_active(self, tmp_path: Path):
        junk = tmp_path / "SomeGame" / "_CommonRedist" / "vcredist"
        junk.mkdir(parents=True)
        (junk / "vc.exe").write_bytes(b"\x00" * 64)

        result = ScanResult(entries=[_make_entry(junk, size=64)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(str(junk)).does_not_exist()


class TestCleanEngineMultipleEntries:
    def test_mixed_existing_and_missing(self, tmp_path: Path):
        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "setup.exe").write_bytes(b"\x00" * 100)
        missing = tmp_path / "missing"

        result = ScanResult(entries=[_make_entry(existing, 100), _make_entry(missing, 200)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.bytes_freed).is_equal_to(100)

    def test_missing_entry_does_not_abort_remaining(self, tmp_path: Path):
        # A non-existent entry must be skipped, not end the loop: a valid entry placed after it
        # still gets cleaned. Pins the `continue` (not `break`) in the path-no-longer-exists branch.
        missing = tmp_path / "already_gone"
        valid = tmp_path / "redist"
        valid.mkdir()
        (valid / "setup.exe").write_bytes(b"\x00" * 100)

        result = ScanResult(entries=[_make_entry(missing, 200), _make_entry(valid, 100)])
        engine = CleanEngine(use_trash=False, dry_run=False)
        stats = engine.clean(result)

        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.deleted).is_equal_to(1)
        assert_that(stats.bytes_freed).is_equal_to(100)
        assert_that(str(valid)).does_not_exist()

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

        assert_that(stats.deleted).is_equal_to(3)
        assert_that(stats.bytes_freed).is_equal_to(768)
        assert_that(all(not (tmp_path / name).exists() for name in ("cache_a", "cache_b", "cache_c"))).is_true()

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

        assert_that(stats.deleted).is_equal_to(1)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.bytes_freed).is_equal_to(100)
        assert_that(str(good)).does_not_exist()
        assert_that(str(bad)).exists()

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

        assert_that(stats.deleted).is_equal_to(2)
        assert_that(stats.bytes_freed).is_equal_to(5100)


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
        assert_that(stats.deleted).is_equal_to(1)

    def test_trash_error_is_captured(self, tmp_path: Path):
        target = tmp_path / "untrashable"
        target.mkdir()

        result = ScanResult(entries=[_make_entry(target)])
        engine = CleanEngine(use_trash=True, dry_run=False)

        with patch("steamcleaner.cleaner.engine.send2trash", side_effect=OSError("trash full")):
            stats = engine.clean(result)

        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors[0]).contains("trash full")

    def test_trashed_bytes_are_not_reported_as_freed(self, tmp_path: Path):
        target = tmp_path / "to_trash"
        target.mkdir()

        engine = CleanEngine(use_trash=True, dry_run=False)
        with patch("steamcleaner.cleaner.engine.send2trash"):
            stats = engine.clean(ScanResult(entries=[_make_entry(target, 700)]))

        assert_that(stats.bytes_trashed).is_equal_to(700)
        assert_that(stats.bytes_freed).is_equal_to(0)

    def test_permanent_deletion_reports_freed_bytes_only(self, tmp_path: Path):
        target = tmp_path / "gone_for_good"
        target.mkdir()

        stats = CleanEngine(use_trash=False, dry_run=False).clean(ScanResult(entries=[_make_entry(target, 700)]))

        assert_that(stats.bytes_freed).is_equal_to(700)
        assert_that(stats.bytes_trashed).is_equal_to(0)


class TestCleanEngineNestedEntries:
    def _nested_pair(self, tmp_path: Path) -> tuple[JunkEntry, JunkEntry]:
        redist = tmp_path / "Game" / "_CommonRedist"
        redist.mkdir(parents=True)
        dump = redist / "crash.dmp"
        dump.write_bytes(b"\x00" * 300)
        return _make_entry(redist, 1000), _make_entry(dump, 300, JunkCategory.CRASH_DUMP)

    def test_child_listed_first_is_not_counted_twice(self, tmp_path: Path):
        parent, child = self._nested_pair(tmp_path)
        callback_log: list[tuple[JunkEntry, bool]] = []

        stats = CleanEngine(use_trash=False, dry_run=False).clean(
            ScanResult(entries=[child, parent]),
            callback=lambda entry, success: callback_log.append((entry, success)),
        )

        assert_that(stats.bytes_freed).is_equal_to(1000)
        assert_that(stats.deleted).is_equal_to(2)
        assert_that(stats.skipped).is_equal_to(0)
        assert_that(callback_log).is_equal_to([(parent, True), (child, True)])
        assert_that(str(parent.path)).does_not_exist()

    def test_entry_after_a_nested_one_is_still_removed(self, tmp_path: Path):
        parent, child = self._nested_pair(tmp_path)
        other_dump = tmp_path / "Game" / "dumps" / "other.dmp"
        other_dump.parent.mkdir()
        other_dump.write_bytes(b"\x00" * 40)
        other = _make_entry(other_dump, 40, JunkCategory.CRASH_DUMP)

        stats = CleanEngine(use_trash=False, dry_run=False).clean(ScanResult(entries=[child, parent, other]))

        assert_that(stats.deleted).is_equal_to(3)
        assert_that(stats.bytes_freed).is_equal_to(1040)
        assert_that(str(other_dump)).does_not_exist()

    def test_dry_run_counts_the_parent_only(self, tmp_path: Path):
        parent, child = self._nested_pair(tmp_path)

        stats = CleanEngine(use_trash=False, dry_run=True).clean(ScanResult(entries=[child, parent]))

        assert_that(stats.bytes_freed).is_equal_to(1000)
        assert_that(stats.deleted).is_equal_to(2)
        assert_that(str(child.path)).exists()

    def test_child_alone_counts_its_own_size(self, tmp_path: Path):
        parent, child = self._nested_pair(tmp_path)

        stats = CleanEngine(use_trash=False, dry_run=False).clean(ScanResult(entries=[child]))

        assert_that(stats.bytes_freed).is_equal_to(300)
        assert_that(str(parent.path)).exists()

    def test_child_of_a_parent_that_failed_is_still_deleted(self, tmp_path: Path):
        parent, child = self._nested_pair(tmp_path)
        engine = CleanEngine(use_trash=False, dry_run=False)

        with patch("steamcleaner.cleaner.engine.shutil.rmtree", side_effect=OSError("locked")):
            stats = engine.clean(ScanResult(entries=[parent, child]))

        assert_that(stats.bytes_freed).is_equal_to(300)
        assert_that(stats.deleted).is_equal_to(1)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(str(child.path)).does_not_exist()


class TestCleanEngineDuplicateEntries:
    def test_same_path_listed_twice_is_removed_and_counted_once(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        entry = _make_entry(target, 700)

        stats = CleanEngine(use_trash=False, dry_run=False).clean(ScanResult(entries=[entry, entry]))

        assert_that(stats.bytes_freed).is_equal_to(700)
        assert_that(stats.deleted).is_equal_to(2)
        assert_that(stats.skipped).is_equal_to(0)

    def test_dry_run_counts_a_repeated_path_once(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        entry = _make_entry(target, 700)

        stats = CleanEngine(use_trash=False, dry_run=True).clean(ScanResult(entries=[entry, entry]))

        assert_that(stats.bytes_freed).is_equal_to(700)
        assert_that(stats.deleted).is_equal_to(2)


class TestCleanEngineMeasuresAtDeletion:
    def _redist_with_two_installers(self, tmp_path: Path) -> Path:
        redist = tmp_path / "redist"
        redist.mkdir()
        (redist / "first.exe").write_bytes(b"\x00" * 600)
        (redist / "second.exe").write_bytes(b"\x00" * 400)
        return redist

    def test_counts_what_is_on_disk_now_not_what_the_scan_recorded(self, tmp_path: Path):
        redist = self._redist_with_two_installers(tmp_path)
        engine = CleanEngine(use_trash=False, dry_run=False, platform=FakePlatformAdapter())

        stats = engine.clean(ScanResult(entries=[_make_entry(redist, 5)]))

        assert_that(stats.bytes_freed).is_equal_to(1000)

    def test_removal_that_fails_part_way_counts_what_did_go(self, tmp_path: Path):
        redist = self._redist_with_two_installers(tmp_path)
        engine = CleanEngine(use_trash=False, dry_run=False, platform=FakePlatformAdapter())

        def remove_first_installer_then_fail(path: Path) -> None:
            (path / "first.exe").unlink()
            raise OSError("second.exe is locked")

        with patch("steamcleaner.cleaner.engine.shutil.rmtree", side_effect=remove_first_installer_then_fail):
            stats = engine.clean(ScanResult(entries=[_make_entry(redist, 1000)]))

        assert_that(stats.bytes_freed).is_equal_to(600)
        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
        assert_that(stats.errors).is_equal_to([f"{redist}: second.exe is locked"])

    def test_removal_that_fails_before_removing_anything_counts_nothing(self, tmp_path: Path):
        redist = self._redist_with_two_installers(tmp_path)
        engine = CleanEngine(use_trash=False, dry_run=False, platform=FakePlatformAdapter())

        with patch("steamcleaner.cleaner.engine.shutil.rmtree", side_effect=OSError("locked")):
            stats = engine.clean(ScanResult(entries=[_make_entry(redist, 1000)]))

        assert_that(stats.bytes_freed).is_equal_to(0)

    def test_file_that_cannot_be_seen_after_a_failure_is_not_counted_as_gone(self, tmp_path: Path, monkeypatch):
        redist = self._redist_with_two_installers(tmp_path)
        engine = CleanEngine(use_trash=False, dry_run=False, platform=FakePlatformAdapter())
        real_lstat = Path.lstat

        def deny_installers(path: Path) -> os.stat_result:
            if path.suffix == ".exe":
                raise PermissionError(f"Access is denied: {path}")
            return real_lstat(path)

        def fail_and_hide_the_files(_path: Path) -> None:
            monkeypatch.setattr(Path, "lstat", deny_installers)
            raise OSError("locked")

        with patch("steamcleaner.cleaner.engine.shutil.rmtree", side_effect=fail_and_hide_the_files):
            stats = engine.clean(ScanResult(entries=[_make_entry(redist, 1000)]))

        assert_that(stats.bytes_freed).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)

    def test_without_a_platform_a_failed_removal_counts_nothing(self, tmp_path: Path):
        redist = self._redist_with_two_installers(tmp_path)

        def remove_first_installer_then_fail(path: Path) -> None:
            (path / "first.exe").unlink()
            raise OSError("second.exe is locked")

        with patch("steamcleaner.cleaner.engine.shutil.rmtree", side_effect=remove_first_installer_then_fail):
            stats = CleanEngine(use_trash=False, dry_run=False).clean(ScanResult(entries=[_make_entry(redist, 1000)]))

        assert_that(stats.bytes_freed).is_equal_to(0)


class TestCleanEngineCallback:
    def test_error_raised_by_the_callback_is_not_recorded_as_a_failed_deletion(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        calls: list[bool] = []

        def failing_callback(_entry: JunkEntry, success: bool) -> None:
            calls.append(success)
            raise OSError("progress bar is gone")

        engine = CleanEngine(use_trash=False, dry_run=False)
        assert_that(engine.clean).raises(OSError).when_called_with(
            ScanResult(entries=[_make_entry(target)]), callback=failing_callback
        ).is_equal_to("progress bar is gone")
        assert_that(calls).is_equal_to([True])
        assert_that(str(target)).does_not_exist()

    @pytest.mark.parametrize(
        ("use_trash", "outcome"), [(False, "freed"), (True, "moved to trash")], ids=["deleted", "trashed"]
    )
    def test_log_says_whether_the_space_was_freed_or_moved_to_the_trash(
        self, tmp_path: Path, caplog, use_trash: bool, outcome: str
    ):
        target = tmp_path / "redist"
        target.mkdir()

        with (
            caplog.at_level(logging.INFO, logger="steamcleaner.cleaner.engine"),
            patch("steamcleaner.cleaner.engine.send2trash"),
        ):
            CleanEngine(use_trash=use_trash, dry_run=False).clean(ScanResult(entries=[_make_entry(target, 700)]))

        assert_that(caplog.messages[-1]).is_equal_to(f"Clean complete: 1 deleted, 0 skipped, 700 bytes {outcome}")

    def test_dry_run_says_in_the_log_that_nothing_was_removed(self, tmp_path: Path, caplog):
        target = tmp_path / "redist"
        target.mkdir()

        with caplog.at_level(logging.INFO, logger="steamcleaner.cleaner.engine"):
            CleanEngine(use_trash=False, dry_run=True).clean(ScanResult(entries=[_make_entry(target, 700)]))

        assert_that(caplog.messages).is_equal_to(
            [
                "Starting clean: 1 entries, dry_run=True, use_trash=False",
                f"Dry run, would remove: {target} (700 bytes)",
                "Dry run complete: would remove 1 entries (700 bytes), 0 skipped",
            ]
        )
