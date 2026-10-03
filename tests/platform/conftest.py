import pytest


@pytest.fixture
def windows_adapter():
    from steamcleaner.platform.windows import WindowsAdapter  # winreg and kernel32 are Windows-only

    return WindowsAdapter()
