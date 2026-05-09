from dataclasses import dataclass, field

from steamcleaner.models.junk import JunkCategory, JunkEntry


@dataclass(slots=True)
class ScanResult:
    entries: list[JunkEntry] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.entries)

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)

    def by_category(self) -> dict[JunkCategory, list[JunkEntry]]:
        result: dict[JunkCategory, list[JunkEntry]] = {}
        for entry in self.entries:
            result.setdefault(entry.category, []).append(entry)
        return result

    def by_client(self) -> dict[str, list[JunkEntry]]:
        result: dict[str, list[JunkEntry]] = {}
        for entry in self.entries:
            result.setdefault(entry.client_name, []).append(entry)
        return result

    def filter_min_size(self, min_bytes: int) -> ScanResult:
        return ScanResult(entries=[entry for entry in self.entries if entry.size_bytes >= min_bytes])

    def merge(self, other: ScanResult) -> ScanResult:
        return ScanResult(entries=self.entries + other.entries)
