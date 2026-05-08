from __future__ import annotations

from pathlib import Path

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult


def _entry(path: str, size: int, category: JunkCategory = JunkCategory.REDISTRIBUTABLE, client: str = "Steam"):
    return JunkEntry(path=Path(path), category=category, size_bytes=size, client_name=client)


class TestJunkEntry:
    def test_frozen(self):
        entry = _entry("/tmp/test", 1024)
        try:
            entry.size_bytes = 0  # type: ignore[misc]
            raise AssertionError("should be frozen")
        except AttributeError:
            pass

    def test_size_mb(self):
        entry = _entry("/tmp/test", 1024 * 1024 * 5)
        assert entry.size_mb == 5.0

    def test_size_mb_fractional(self):
        entry = _entry("/tmp/test", 1024 * 512)
        assert entry.size_mb == 0.5


class TestScanResult:
    def test_empty(self):
        result = ScanResult()
        assert result.total_bytes == 0
        assert result.total_mb == 0.0
        assert result.entries == []

    def test_total_bytes(self):
        result = ScanResult(entries=[_entry("/a", 100), _entry("/b", 200)])
        assert result.total_bytes == 300

    def test_by_category(self):
        entries = [
            _entry("/a", 100, JunkCategory.REDISTRIBUTABLE),
            _entry("/b", 200, JunkCategory.SHADER_CACHE),
            _entry("/c", 300, JunkCategory.REDISTRIBUTABLE),
        ]
        result = ScanResult(entries=entries)
        grouped = result.by_category()
        assert len(grouped[JunkCategory.REDISTRIBUTABLE]) == 2
        assert len(grouped[JunkCategory.SHADER_CACHE]) == 1

    def test_by_client(self):
        entries = [
            _entry("/a", 100, client="Steam"),
            _entry("/b", 200, client="Epic"),
            _entry("/c", 300, client="Steam"),
        ]
        result = ScanResult(entries=entries)
        grouped = result.by_client()
        assert len(grouped["Steam"]) == 2
        assert len(grouped["Epic"]) == 1

    def test_filter_min_size(self):
        entries = [_entry("/a", 100), _entry("/b", 5000), _entry("/c", 50)]
        result = ScanResult(entries=entries)
        filtered = result.filter_min_size(100)
        assert len(filtered.entries) == 2

    def test_merge(self):
        r1 = ScanResult(entries=[_entry("/a", 100)])
        r2 = ScanResult(entries=[_entry("/b", 200)])
        merged = r1.merge(r2)
        assert len(merged.entries) == 2
        assert merged.total_bytes == 300
