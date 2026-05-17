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

    def wine_prefixes(self) -> list[Path]:
        prefixes: list[Path] = []
        home = self.home()

        default_wine = home / ".wine" / "drive_c"
        if default_wine.is_dir():
            prefixes.append(default_wine)

        for bottles_root in (
            home / "Library" / "Application Support" / "CrossOver" / "Bottles",
            home / "Library" / "Containers" / "com.isaacmarovitz.Whisky" / "Bottles",
            home / "Library" / "PlayOnMac" / "wineprefix",
        ):
            if bottles_root.is_dir():
                for bottle_dir in bottles_root.iterdir():
                    drive_c = bottle_dir / "drive_c"
                    if drive_c.is_dir() and drive_c not in prefixes:
                        prefixes.append(drive_c)

        return prefixes
