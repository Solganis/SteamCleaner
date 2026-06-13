from assertpy2 import assert_that

from steamcleaner.models.junk import JunkCategory
from steamcleaner.scanner.patterns import COMMON_PATTERNS, JunkPattern


class TestJunkPattern:
    def test_pattern_is_frozen(self):
        pattern = COMMON_PATTERNS[0]
        assert_that(pattern).is_instance_of(JunkPattern)

    def test_redist_pattern_matches(self):
        pattern = COMMON_PATTERNS[0]
        assert_that(pattern.dir_regex.search("_CommonRedist")).is_true()
        assert_that(pattern.dir_regex.search("DirectX")).is_true()
        assert_that(pattern.dir_regex.search("redist")).is_true()
        assert_that(pattern.dir_regex.search("gamedata")).is_false()

    def test_redist_extensions(self):
        pattern = COMMON_PATTERNS[0]
        assert_that(pattern.file_extensions).contains(".exe")
        assert_that(pattern.file_extensions).contains(".cab")
        assert_that(pattern.file_extensions).contains(".msi")

    def test_installer_pattern(self):
        pattern = COMMON_PATTERNS[1]
        assert_that(pattern.category).is_equal_to(JunkCategory.INSTALLER)
        assert_that(pattern.dir_regex.search("installer")).is_true()
        assert_that(pattern.dir_regex.search("Setup")).is_true()

    def test_cross_platform_pattern(self):
        pattern = COMMON_PATTERNS[2]
        assert_that(pattern.category).is_equal_to(JunkCategory.CROSS_PLATFORM)
        assert_that(pattern.dir_regex.search("lib/darwin-x86_64")).is_true()
        assert_that(pattern.dir_regex.search("lib/linux-x86_64")).is_true()
        assert_that(pattern.dir_regex.search("lib/windows")).is_false()

    def test_shader_cache_pattern(self):
        pattern = COMMON_PATTERNS[3]
        assert_that(pattern.category).is_equal_to(JunkCategory.SHADER_CACHE)
        assert_that(pattern.dir_regex.search("shadercache")).is_true()
        assert_that(pattern.dir_regex.search("shader_cache")).is_true()
        assert_that(pattern.file_extensions).is_length(0)

    def test_all_patterns_have_descriptions(self):
        for pattern in COMMON_PATTERNS:
            assert_that(pattern.description).is_true()
            assert_that(pattern.category).is_instance_of(JunkCategory)
