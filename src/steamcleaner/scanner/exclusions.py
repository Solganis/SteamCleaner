import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import PurePath

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class Exclusion:
    pattern: str
    reason: str


BUILTIN_EXCLUSIONS: Final[tuple[Exclusion, ...]] = (
    Exclusion(pattern="Steamworks Shared", reason="Shared redistributable pool, removing breaks games (issue #74)"),
    Exclusion(pattern="Heroes of the Storm", reason="Game files stored in support/ directory"),
    Exclusion(pattern="StarCraft", reason="Game files stored in support/ directory"),
    Exclusion(pattern="Penumbra Overture/redist", reason="Contains actual game data, not redistributables"),
    Exclusion(pattern="Medieval II Total War/miles", reason="Miles Sound System is part of the game engine"),
)


@dataclass(slots=True)
class ExclusionRegistry:
    _exclusions: list[Exclusion] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._exclusions.extend(BUILTIN_EXCLUSIONS)

    def add(self, pattern: str, reason: str) -> None:
        self._exclusions.append(Exclusion(pattern=pattern, reason=reason))

    def is_excluded(self, path: PurePath) -> bool:
        path_str = str(path).replace("\\", "/").lower()
        for exclusion in self._exclusions:
            if exclusion.pattern.lower() in path_str:
                _logger.debug("Path excluded by '%s': %s", exclusion.pattern, path)
                return True
        return False

    @property
    def all(self) -> list[Exclusion]:
        return list(self._exclusions)
