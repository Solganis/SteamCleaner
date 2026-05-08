from __future__ import annotations

from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.patterns import COMMON_PATTERNS, JunkPattern


class TestJunkPattern:
    def test_pattern_is_frozen(self):
        pattern = COMMON_PATTERNS[0]
        assert isinstance(pattern, JunkPattern)

    def test_redist_pattern_matches(self):
        pattern = COMMON_PATTERNS[0]
        assert pattern.dir_regex.search("_CommonRedist")
        assert pattern.dir_regex.search("DirectX")
        assert pattern.dir_regex.search("redist")
        assert not pattern.dir_regex.search("gamedata")

    def test_redist_extensions(self):
        pattern = COMMON_PATTERNS[0]
        assert ".exe" in pattern.file_extensions
        assert ".cab" in pattern.file_extensions
        assert ".msi" in pattern.file_extensions

    def test_installer_pattern(self):
        pattern = COMMON_PATTERNS[1]
        assert pattern.category == JunkCategory.INSTALLER
        assert pattern.dir_regex.search("installer")
        assert pattern.dir_regex.search("Setup")

    def test_cross_platform_pattern(self):
        pattern = COMMON_PATTERNS[2]
        assert pattern.category == JunkCategory.CROSS_PLATFORM
        assert pattern.dir_regex.search("lib/darwin-x86_64")
        assert pattern.dir_regex.search("lib/linux-x86_64")
        assert not pattern.dir_regex.search("lib/windows")

    def test_shader_cache_pattern(self):
        pattern = COMMON_PATTERNS[3]
        assert pattern.category == JunkCategory.SHADER_CACHE
        assert pattern.dir_regex.search("shadercache")
        assert pattern.dir_regex.search("shader_cache")
        assert len(pattern.file_extensions) == 0

    def test_all_patterns_have_descriptions(self):
        for pattern in COMMON_PATTERNS:
            assert pattern.description
            assert isinstance(pattern.category, JunkCategory)
