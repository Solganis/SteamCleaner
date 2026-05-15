import logging
from dataclasses import dataclass, field
from pathlib import PurePath

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Exclusion:
    pattern: str
    reason: str


BUILTIN_EXCLUSIONS: tuple[Exclusion, ...] = (
    Exclusion("Steamworks Shared", "Shared redistributable pool, removing breaks games (issue #74)"),
    Exclusion("Heroes of the Storm", "Game files stored in support/ directory"),
    Exclusion("StarCraft", "Game files stored in support/ directory"),
    Exclusion("Penumbra Overture/redist", "Contains actual game data, not redistributables"),
    Exclusion("Medieval II Total War/miles", "Miles Sound System is part of the game engine"),
)


@dataclass(slots=True)
class ExclusionRegistry:
    _exclusions: list[Exclusion] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._exclusions.extend(BUILTIN_EXCLUSIONS)

    def add(self, pattern: str, reason: str) -> None:
        self._exclusions.append(Exclusion(pattern, reason))

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
