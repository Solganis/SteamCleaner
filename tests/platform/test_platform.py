import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from assertpy2 import assert_that

from steamcleaner.platform import create_adapter
from steamcleaner.platform.linux import LinuxAdapter
from steamcleaner.platform.macos import MacOSAdapter


class TestCreateAdapter:
    def test_linux_returns_linux_adapter(self):
        with patch.object(sys, "platform", "linux"):
            adapter = create_adapter()
        assert_that(adapter).is_instance_of(LinuxAdapter)

    def test_win32_returns_windows_adapter(self):
        if sys.platform != "win32":
            pytest.skip("Windows-only test")
        adapter = create_adapter()
        from steamcleaner.platform.windows import WindowsAdapter  # winreg is Windows-only

        assert_that(adapter).is_instance_of(WindowsAdapter)

    def test_darwin_returns_macos_adapter(self):
        with patch.object(sys, "platform", "darwin"):
            adapter = create_adapter()
        assert_that(adapter).is_instance_of(MacOSAdapter)

    def test_unsupported_platform_raises(self):
        with patch.object(sys, "platform", "freebsd"), pytest.raises(RuntimeError, match="Unsupported platform"):
            create_adapter()


class TestLinuxAdapterProgramFiles:
    def test_returns_existing_dirs(self, tmp_path: Path):
        adapter = LinuxAdapter()
        with (
            patch("steamcleaner.platform.linux.Path.is_dir", return_value=True),
        ):
            paths = adapter.program_files()
            assert_that(paths).is_not_empty()

    def test_skips_nonexistent_dirs(self):
        adapter = LinuxAdapter()
        with patch("steamcleaner.platform.linux.Path.is_dir", return_value=False):
            paths = adapter.program_files()
            assert_that(paths).is_equal_to([])


class TestBaseAdapterWinePrefixes:
    def test_default_wine_prefixes_returns_empty(self):
        if sys.platform != "win32":
            pytest.skip("Windows-only test")
        adapter = create_adapter()
        assert_that(adapter.wine_prefixes()).is_equal_to([])
