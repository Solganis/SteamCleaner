"""Property-based tests for ExclusionRegistry, the last guard against deleting real game data.

The example tests in test_exclusions.py pin specific paths; these check the invariants that must
hold for *any* path: a builtin (or user-added) pattern embedded anywhere always excludes, the
verdict is invariant under case and slash direction, and a path built only from pattern-free
segments is never excluded.
"""

from pathlib import PurePosixPath, PureWindowsPath

from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st

from steamcleaner.scanner.exclusions import BUILTIN_EXCLUSIONS, ExclusionRegistry

_BUILTIN_PATTERNS = [exclusion.pattern for exclusion in BUILTIN_EXCLUSIONS]

# Segments that provably share no substring with any builtin pattern, so a path assembled from
# them must never be excluded. None of the multi-word builtin phrases can span the "/" joins.
_SAFE_SEGMENTS = ("common", "SomeGame", "data", "cache", "redist", "_CommonRedist", "bin", "app")
_safe_segment = st.sampled_from(_SAFE_SEGMENTS)
_filler = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 _-", max_size=6)


def _embed(pattern: str, prefix: str, suffix: str, separator: str) -> str:
    """Join non-empty filler segments around pattern so the result embeds pattern verbatim."""
    parts = [part for part in (prefix, pattern, suffix) if part]
    return separator.join(parts)


class TestExclusionMatchInvariants:
    @given(builtin=st.sampled_from(_BUILTIN_PATTERNS), prefix=_filler, suffix=_filler)
    def test_embedded_builtin_pattern_is_always_excluded(self, builtin, prefix, suffix):
        registry = ExclusionRegistry()
        path = PurePosixPath(_embed(builtin, prefix, suffix, "/"))
        assert_that(registry.is_excluded(path)).is_true()

    @given(builtin=st.sampled_from(_BUILTIN_PATTERNS), prefix=_filler, suffix=_filler)
    def test_verdict_is_case_invariant(self, builtin, prefix, suffix):
        registry = ExclusionRegistry()
        path_str = _embed(builtin, prefix, suffix, "/")
        baseline = registry.is_excluded(PurePosixPath(path_str))
        assert_that(registry.is_excluded(PurePosixPath(path_str.upper()))).is_equal_to(baseline)
        assert_that(registry.is_excluded(PurePosixPath(path_str.lower()))).is_equal_to(baseline)

    @given(builtin=st.sampled_from(_BUILTIN_PATTERNS), prefix=_filler, suffix=_filler)
    def test_verdict_is_slash_invariant(self, builtin, prefix, suffix):
        registry = ExclusionRegistry()
        posix_path = PurePosixPath(_embed(builtin, prefix, suffix, "/"))
        windows_path = PureWindowsPath(_embed(builtin, prefix, suffix, "\\"))
        assert_that(registry.is_excluded(posix_path)).is_true()
        assert_that(registry.is_excluded(windows_path)).is_true()

    @given(segments=st.lists(_safe_segment, min_size=1, max_size=6))
    def test_pattern_free_path_is_never_excluded(self, segments):
        registry = ExclusionRegistry()
        path = PurePosixPath("/".join(segments))
        assert_that(registry.is_excluded(path)).is_false()

    @given(
        pattern=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=3, max_size=10),
        prefix=_filler,
        suffix=_filler,
    )
    def test_added_exclusion_substring_always_matches(self, pattern, prefix, suffix):
        registry = ExclusionRegistry()
        registry.add(pattern, "user-defined exclusion")
        path = PurePosixPath(_embed(pattern, prefix, suffix, "/"))
        assert_that(registry.is_excluded(path)).is_true()
