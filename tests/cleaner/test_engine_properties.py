"""Property-based tests for CleanEngine's reparse-point safety gate.

The example tests cover single symlinks; this checks the gate holds for *any* configuration:
across an arbitrary mix of plain and reparse-flagged directories, the engine deletes exactly the
plain ones, never touches a reparse point, and keeps its deleted/skipped/bytes counters consistent.
"""

import uuid
from pathlib import Path

from assertpy2 import assert_that
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.exclusions import BUILTIN_EXCLUSIONS

_ENTRY_SIZE = 64
_BUILTIN_PATTERNS = [exclusion.pattern for exclusion in BUILTIN_EXCLUSIONS]


def _make_entry(path: Path) -> JunkEntry:
    return JunkEntry(path=path, category=JunkCategory.REDISTRIBUTABLE, size_bytes=_ENTRY_SIZE, client_name="Steam")


class TestCleanEngineReparseGateProperties:
    @given(reparse_flags=st.lists(st.booleans(), min_size=1, max_size=6))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=60)
    def test_reparse_points_survive_others_are_cleaned(self, reparse_flags, tmp_path, monkeypatch):
        # tmp_path is resolved once and shared across hypothesis examples, so isolate each
        # example in its own subtree to avoid cross-example collisions.
        root = tmp_path / uuid.uuid4().hex
        root.mkdir()

        directories: list[Path] = []
        reparse_set: set[Path] = set()
        for index, is_reparse in enumerate(reparse_flags):
            target = root / f"dir_{index}"
            target.mkdir()
            (target / "file.bin").write_bytes(b"\x00" * _ENTRY_SIZE)
            directories.append(target)
            if is_reparse:
                reparse_set.add(target)

        # Simulate the reparse subset at the safety primitive: real junctions need privileges on
        # Windows, and is_reparse_point itself is unit-tested with real symlinks elsewhere.
        monkeypatch.setattr("steamcleaner.cleaner.engine.is_reparse_point", lambda path: path in reparse_set)

        result = ScanResult(entries=[_make_entry(target) for target in directories])
        stats = CleanEngine(use_trash=False, dry_run=False).clean(result)

        cleaned = [target for target in directories if target not in reparse_set]
        for survivor in reparse_set:
            assert_that(str(survivor)).exists()
        for removed in cleaned:
            assert_that(str(removed)).does_not_exist()
        assert_that(stats.skipped).is_equal_to(len(reparse_set))
        assert_that(stats.deleted).is_equal_to(len(cleaned))
        assert_that(stats.bytes_freed).is_equal_to(_ENTRY_SIZE * len(cleaned))


class TestCleanEngineExclusionGateProperties:
    @given(builtin=st.sampled_from(_BUILTIN_PATTERNS), before=st.booleans(), after=st.booleans())
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None, max_examples=40)
    def test_builtin_excluded_path_is_never_deleted(self, builtin, before, after, tmp_path, monkeypatch):
        # No monkeypatch on is_reparse_point here: these are real, plain directories, so the ONLY
        # thing that can keep them alive is the exclusion gate. Real junctions need privileges.
        root = tmp_path / uuid.uuid4().hex
        # Optional filler segments around the pattern confirm a substring match guards, not an exact path.
        relative = "/".join(part for part in ("outer" if before else "", builtin, "inner" if after else "") if part)
        target = root / relative
        target.mkdir(parents=True)
        (target / "data.bin").write_bytes(b"\x00" * _ENTRY_SIZE)

        result = ScanResult(entries=[_make_entry(target)])
        stats = CleanEngine(use_trash=False, dry_run=False).clean(result)

        assert_that(str(target)).exists()
        assert_that(stats.deleted).is_equal_to(0)
        assert_that(stats.skipped).is_equal_to(1)
