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
_sibling_entry = st.builds(
    JunkEntry,
    path=st.builds(Path, st.text(alphabet="abcdefghijklmnop_-", min_size=1, max_size=12)),
    category=st.sampled_from(list(JunkCategory)),
    size_bytes=st.integers(min_value=0, max_value=10**12),
    client_name=st.just("Steam"),
)
_sibling_list = st.lists(_sibling_entry, max_size=30, unique_by=lambda entry: entry.path)


class TestScanResultAggregation:
    @given(_sibling_list)
    def test_total_bytes_of_unrelated_paths_is_the_sum_of_sizes(self, entries):
        result = ScanResult(entries=entries)
        assert_that(result.total_bytes).is_equal_to(sum(entry.size_bytes for entry in entries))

    @given(_sibling_list.filter(bool), st.integers(min_value=0, max_value=10**12), st.data())
    def test_entry_nested_under_another_adds_nothing(self, entries, nested_size, data):
        parent = data.draw(st.sampled_from(entries))
        nested = JunkEntry(
            path=parent.path / "nested" / "dump.dmp",
            category=JunkCategory.CRASH_DUMP,
            size_bytes=nested_size,
            client_name="Steam",
        )
        assert_that(ScanResult(entries=[nested, *entries]).total_bytes).is_equal_to(
            ScanResult(entries=entries).total_bytes
        )

    @given(_sibling_list.filter(bool), st.data())
    def test_same_path_listed_twice_counts_once(self, entries, data):
        repeated = data.draw(st.sampled_from(entries))
        assert_that(ScanResult(entries=[*entries, repeated]).total_bytes).is_equal_to(
            ScanResult(entries=entries).total_bytes
        )

    @given(_entry_list)
    def test_total_bytes_never_exceeds_the_sum_of_sizes(self, entries):
        result = ScanResult(entries=entries)
        assert_that(result.total_bytes).is_less_than_or_equal_to(sum(entry.size_bytes for entry in entries))

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
    def test_merge_keeps_every_entry_and_never_inflates_the_total(self, left_entries, right_entries):
        left = ScanResult(entries=left_entries)
        right = ScanResult(entries=right_entries)
        merged = left.merge(right)
        assert_that(len(merged.entries)).is_equal_to(len(left_entries) + len(right_entries))
        assert_that(merged.total_bytes).is_less_than_or_equal_to(left.total_bytes + right.total_bytes)
