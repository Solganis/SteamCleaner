from pathlib import PurePosixPath, PureWindowsPath

from assertpy2 import assert_that

from steamcleaner.scanner.exclusions import BUILTIN_EXCLUSIONS, ExclusionRegistry


class TestBuiltinExclusions:
    def test_steamworks_shared(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\steamapps\common\Steamworks Shared\redist")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_heroes_of_the_storm(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"C:\Games\Heroes of the Storm\support\directx.cab")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_starcraft(self, exclusion_registry: ExclusionRegistry):
        path = PurePosixPath("/games/StarCraft/support/installer.exe")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_penumbra_overture(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\Penumbra Overture\redist\data.bin")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_medieval_total_war(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\Medieval II Total War\miles\sound.dll")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_all_builtins_loaded(self, exclusion_registry: ExclusionRegistry):
        assert_that(len(exclusion_registry.all)).is_greater_than_or_equal_to(len(BUILTIN_EXCLUSIONS))


class TestExclusionRegistry:
    def test_non_excluded_path(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\SomeGame\_CommonRedist\vcredist.exe")
        assert_that(exclusion_registry.is_excluded(path)).is_false()

    def test_custom_exclusion(self, exclusion_registry: ExclusionRegistry):
        exclusion_registry.add("MySpecialGame/redist", "Contains game data")
        path = PureWindowsPath(r"D:\Steam\common\MySpecialGame\redist\file.dll")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_case_insensitive(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\STEAMWORKS SHARED\redist")
        assert_that(exclusion_registry.is_excluded(path)).is_true()

    def test_forward_slash_normalization(self, exclusion_registry: ExclusionRegistry):
        path = PurePosixPath("/games/Medieval II Total War/miles/sound.dll")
        assert_that(exclusion_registry.is_excluded(path)).is_true()
