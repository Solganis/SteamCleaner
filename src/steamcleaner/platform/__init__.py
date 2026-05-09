import sys

from steamcleaner.platform.base import PlatformAdapter


def create_adapter() -> PlatformAdapter:
    match sys.platform:
        case "win32":
            from steamcleaner.platform.windows import WindowsAdapter

            return WindowsAdapter()
        case "linux":
            from steamcleaner.platform.linux import LinuxAdapter

            return LinuxAdapter()
        case _:
            raise RuntimeError(f"Unsupported platform: {sys.platform}")
