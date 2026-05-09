import enum
from dataclasses import dataclass
from pathlib import Path


class JunkCategory(enum.StrEnum):
    REDISTRIBUTABLE = "redistributable"
    SHADER_CACHE = "shader_cache"
    CRASH_DUMP = "crash_dump"
    OLD_LOG = "old_log"
    CROSS_PLATFORM = "cross_platform"
    INSTALLER = "installer"


@dataclass(frozen=True, slots=True)
class JunkEntry:
    path: Path
    category: JunkCategory
    size_bytes: int
    client_name: str
    description: str = ""

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)
