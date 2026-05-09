from pathlib import Path

from steamcleaner.platform.base import PlatformAdapter


class MacOSAdapter(PlatformAdapter):
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        return None

    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        return []

    def appdata_local(self) -> Path:
        return Path.home() / "Library" / "Application Support"

    def appdata_roaming(self) -> Path:
        return Path.home() / "Library" / "Application Support"

    def home(self) -> Path:
        return Path.home()

    def program_files(self) -> list[Path]:
        apps = Path("/Applications")
        if apps.is_dir():
            return [apps]
        return []

    def programdata(self) -> Path:
        return Path("/Users/Shared")
