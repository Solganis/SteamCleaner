import sys

from steamcleaner.platform.base import PlatformAdapter


def create_adapter() -> PlatformAdapter:
    match sys.platform:
        case "win32":  # pragma: no cover - Windows-only branch (winreg); tested on the Windows CI runner
            from steamcleaner.platform.windows import WindowsAdapter

            return WindowsAdapter()
        case "linux":
            from steamcleaner.platform.linux import LinuxAdapter

            return LinuxAdapter()
        case "darwin":
            from steamcleaner.platform.macos import MacOSAdapter

            return MacOSAdapter()
        case _:
            raise RuntimeError(f"Unsupported platform: {sys.platform}")
