from __future__ import annotations

import re
from dataclasses import dataclass

from steamcleaner.models.junk import JunkCategory


@dataclass(frozen=True, slots=True)
class JunkPattern:
    dir_regex: re.Pattern[str]
    file_extensions: frozenset[str]
    category: JunkCategory
    description: str


COMMON_PATTERNS: tuple[JunkPattern, ...] = (
    JunkPattern(
        dir_regex=re.compile(r"(directx|redist|_commonredist)", re.IGNORECASE),
        file_extensions=frozenset({".cab", ".exe", ".msi"}),
        category=JunkCategory.REDISTRIBUTABLE,
        description="DirectX/VC++ redistributable installers",
    ),
    JunkPattern(
        dir_regex=re.compile(r"(installer|setup)", re.IGNORECASE),
        file_extensions=frozenset({".exe", ".msi"}),
        category=JunkCategory.INSTALLER,
        description="Bundled installers",
    ),
    JunkPattern(
        dir_regex=re.compile(r"lib/(darwin|linux)-", re.IGNORECASE),
        file_extensions=frozenset({".so", ".dylib"}),
        category=JunkCategory.CROSS_PLATFORM,
        description="Ren'Py cross-platform binaries",
    ),
    JunkPattern(
        dir_regex=re.compile(r"shader_?cache", re.IGNORECASE),
        file_extensions=frozenset(),
        category=JunkCategory.SHADER_CACHE,
        description="Shader cache directories",
    ),
)
