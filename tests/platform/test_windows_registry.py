import sys

import pytest
from assertpy2 import assert_that

ONLY_WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="the Windows adapter calls winreg")
CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"


def _query_32_bit_view(value_name: str) -> tuple[object, int]:
    """Read a value of the CurrentVersion key straight from winreg, as (value, type)."""
    import winreg  # Windows-only module

    access = winreg.KEY_READ | winreg.KEY_WOW64_32KEY
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CURRENT_VERSION, 0, access) as reg_key:
        return winreg.QueryValueEx(reg_key, value_name)


@ONLY_WINDOWS
class TestWindowsRegistryDword:
    def test_missing_key_reads_as_none(self, windows_adapter):
        import winreg  # Windows-only module

        missing_key = r"Software\SteamCleanerTests\Missing"
        access = winreg.KEY_READ | winreg.KEY_WOW64_32KEY
        assert_that(winreg.OpenKey).raises(FileNotFoundError).when_called_with(
            winreg.HKEY_LOCAL_MACHINE, missing_key, 0, access
        )
        assert_that(windows_adapter.read_registry_dword("HKLM", missing_key, "Step")).is_none()

    def test_missing_value_of_an_existing_key_reads_as_none(self, windows_adapter):
        import winreg  # Windows-only module

        access = winreg.KEY_READ | winreg.KEY_WOW64_32KEY
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CURRENT_VERSION, 0, access) as existing_key:
            assert_that(winreg.QueryValueEx).raises(FileNotFoundError).when_called_with(
                existing_key, "SteamCleanerTestsMissing"
            )
        assert_that(windows_adapter.read_registry_dword("HKLM", CURRENT_VERSION, "SteamCleanerTestsMissing")).is_none()

    def test_unknown_hive_reads_as_none(self, windows_adapter):
        assert_that(windows_adapter.read_registry_dword("HKXX", r"Software\Microsoft", "Step")).is_none()

    def test_value_that_is_not_a_dword_reads_as_none(self, windows_adapter):
        import winreg  # Windows-only module

        assert_that(_query_32_bit_view("ProductName")[1]).is_equal_to(winreg.REG_SZ)
        assert_that(windows_adapter.read_registry_dword("HKLM", CURRENT_VERSION, "ProductName")).is_none()

    def test_dword_is_read_with_its_value(self, windows_adapter):
        import winreg  # Windows-only module

        value, value_type = _query_32_bit_view("CurrentMajorVersionNumber")
        assert_that(value_type).is_equal_to(winreg.REG_DWORD)
        assert_that(
            windows_adapter.read_registry_dword("HKLM", CURRENT_VERSION, "CurrentMajorVersionNumber")
        ).is_equal_to(value)

    def test_windows_has_a_registry(self, windows_adapter):
        assert_that(windows_adapter.has_registry()).is_true()

    def test_dword_is_read_through_the_32_bit_view(self, windows_adapter, monkeypatch):
        import winreg  # Windows-only module

        access_masks: list[int] = []
        open_key = winreg.OpenKey

        def record_and_open(key: int, subkey: str, reserved: int, access: int) -> winreg.HKEYType:
            access_masks.append(access)
            return open_key(key, subkey, reserved, access)

        monkeypatch.setattr(winreg, "OpenKey", record_and_open)
        windows_adapter.read_registry_dword("HKLM", CURRENT_VERSION, "Step")
        assert_that(access_masks).is_equal_to([winreg.KEY_READ | winreg.KEY_WOW64_32KEY])
