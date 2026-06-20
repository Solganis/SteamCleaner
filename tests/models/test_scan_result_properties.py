"""Property-based tests for ScanResult, the contract between ScanEngine and CleanEngine.

These guard the aggregation laws against future refactors: totals stay additive,
grouping is a true partition (every entry lands in exactly one bucket), filtering
only ever drops entries below the threshold, and merge concatenates without loss.
"""

from pathlib import Path

from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult

_junk_entry = st.builds(
    JunkEntry,
    path=st.builds(Path, st.text(alphabet="abcdefghijklmnop/._-", min_size=1, max_size=12)),
    category=st.sampled_from(list(JunkCategory)),
    size_bytes=st.integers(min_value=0, max_value=10**12),
    client_name=st.sampled_from(["Steam", "Epic", "GOG", "EA App", "Ubisoft Connect"]),
)
_entry_list = st.lists(_junk_entry, max_size=30)


class TestScanResultAggregation:
    @given(_entry_list)
    def test_total_bytes_equals_sum_of_sizes(self, entries):
        result = ScanResult(entries=entries)
        assert_that(result.total_bytes).is_equal_to(sum(entry.size_bytes for entry in entries))

    @given(_entry_list)
    def test_total_mb_tracks_total_bytes(self, entries):
        result = ScanResult(entries=entries)
        assert_that(result.total_mb).is_equal_to(result.total_bytes / (1024 * 1024))

    @given(_entry_list)
    def test_by_category_is_a_partition(self, entries):
        groups = ScanResult(entries=entries).by_category()
        regrouped = [entry for bucket in groups.values() for entry in bucket]
        assert_that(len(regrouped)).is_equal_to(len(entries))
        for category, bucket in groups.items():
            for entry in bucket:
                assert_that(entry.category).is_equal_to(category)

    @given(_entry_list)
    def test_by_client_is_a_partition(self, entries):
        groups = ScanResult(entries=entries).by_client()
        regrouped = [entry for bucket in groups.values() for entry in bucket]
        assert_that(len(regrouped)).is_equal_to(len(entries))
        for client_name, bucket in groups.items():
            for entry in bucket:
                assert_that(entry.client_name).is_equal_to(client_name)

    @given(_entry_list, st.integers(min_value=0, max_value=10**12))
    def test_filter_min_size_keeps_only_large_enough(self, entries, min_bytes):
        filtered = ScanResult(entries=entries).filter_min_size(min_bytes)
        for entry in filtered.entries:
            assert_that(entry.size_bytes).is_greater_than_or_equal_to(min_bytes)
        assert_that(filtered.total_bytes).is_less_than_or_equal_to(sum(entry.size_bytes for entry in entries))

    @given(_entry_list, _entry_list)
    def test_merge_is_additive(self, left_entries, right_entries):
        left = ScanResult(entries=left_entries)
        right = ScanResult(entries=right_entries)
        merged = left.merge(right)
        assert_that(len(merged.entries)).is_equal_to(len(left_entries) + len(right_entries))
        assert_that(merged.total_bytes).is_equal_to(left.total_bytes + right.total_bytes)
