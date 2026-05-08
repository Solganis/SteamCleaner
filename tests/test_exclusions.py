from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

from steamcleaner.scanner.exclusions import BUILTIN_EXCLUSIONS, ExclusionRegistry


class TestBuiltinExclusions:
    def test_steamworks_shared(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\steamapps\common\Steamworks Shared\redist")
        assert exclusion_registry.is_excluded(path)

    def test_heroes_of_the_storm(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"C:\Games\Heroes of the Storm\support\directx.cab")
        assert exclusion_registry.is_excluded(path)

    def test_starcraft(self, exclusion_registry: ExclusionRegistry):
        path = PurePosixPath("/games/StarCraft/support/installer.exe")
        assert exclusion_registry.is_excluded(path)

    def test_penumbra_overture(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\Penumbra Overture\redist\data.bin")
        assert exclusion_registry.is_excluded(path)

    def test_medieval_total_war(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\Medieval II Total War\miles\sound.dll")
        assert exclusion_registry.is_excluded(path)

    def test_all_builtins_loaded(self, exclusion_registry: ExclusionRegistry):
        assert len(exclusion_registry.all) >= len(BUILTIN_EXCLUSIONS)


class TestExclusionRegistry:
    def test_non_excluded_path(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\SomeGame\_CommonRedist\vcredist.exe")
        assert not exclusion_registry.is_excluded(path)

    def test_custom_exclusion(self, exclusion_registry: ExclusionRegistry):
        exclusion_registry.add("MySpecialGame/redist", "Contains game data")
        path = PureWindowsPath(r"D:\Steam\common\MySpecialGame\redist\file.dll")
        assert exclusion_registry.is_excluded(path)

    def test_case_insensitive(self, exclusion_registry: ExclusionRegistry):
        path = PureWindowsPath(r"D:\Steam\common\STEAMWORKS SHARED\redist")
        assert exclusion_registry.is_excluded(path)

    def test_forward_slash_normalization(self, exclusion_registry: ExclusionRegistry):
        path = PurePosixPath("/games/Medieval II Total War/miles/sound.dll")
        assert exclusion_registry.is_excluded(path)
