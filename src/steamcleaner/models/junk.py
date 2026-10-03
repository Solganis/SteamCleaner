import enum
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final


class JunkCategory(enum.StrEnum):
    REDISTRIBUTABLE = "redistributable"
    SHADER_CACHE = "shader_cache"
    CRASH_DUMP = "crash_dump"
    OLD_LOG = "old_log"
    CROSS_PLATFORM = "cross_platform"
    INSTALLER = "installer"
    LEFTOVER = "leftover"


GUARDED_CATEGORIES: Final = frozenset({JunkCategory.LEFTOVER})


@dataclass(frozen=True, slots=True, kw_only=True)
class JunkEntry:
    path: Path
    category: JunkCategory
    size_bytes: int
    client_name: str
    description: str = ""
    game_root: Path | None = None
    display_name: str | None = None
    last_written: date | None = None

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)
