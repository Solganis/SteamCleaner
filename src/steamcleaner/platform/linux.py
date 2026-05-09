import os
from pathlib import Path

from steamcleaner.platform.base import PlatformAdapter


class LinuxAdapter(PlatformAdapter):
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        return None

    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        return []

    def appdata_local(self) -> Path:
        return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    def appdata_roaming(self) -> Path:
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

    def home(self) -> Path:
        return Path.home()

    def program_files(self) -> list[Path]:
        paths = []
        for directory in ("/usr/local/share", "/usr/share", "/opt"):
            dir_path = Path(directory)
            if dir_path.is_dir():
                paths.append(dir_path)
        return paths

    def programdata(self) -> Path:
        return Path("/var/lib")

    def wine_prefixes(self) -> list[Path]:
        prefixes: list[Path] = []
        home = self.home()

        default_wine = home / ".wine" / "drive_c"
        if default_wine.is_dir():
            prefixes.append(default_wine)

        compatdata = home / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        if compatdata.is_dir():
            for app_dir in compatdata.iterdir():
                drive_c = app_dir / "pfx" / "drive_c"
                if drive_c.is_dir() and drive_c not in prefixes:
                    prefixes.append(drive_c)

        flatpak_compatdata = (
            home
            / ".var"
            / "app"
            / "com.valvesoftware.Steam"
            / ".local"
            / "share"
            / "Steam"
            / "steamapps"
            / "compatdata"
        )
        if flatpak_compatdata.is_dir():
            for app_dir in flatpak_compatdata.iterdir():
                drive_c = app_dir / "pfx" / "drive_c"
                if drive_c.is_dir() and drive_c not in prefixes:
                    prefixes.append(drive_c)

        for bottles_root in (
            home / ".local" / "share" / "bottles" / "bottles",
            home / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles" / "bottles",
        ):
            if bottles_root.is_dir():
                for bottle_dir in bottles_root.iterdir():
                    drive_c = bottle_dir / "drive_c"
                    if drive_c.is_dir() and drive_c not in prefixes:
                        prefixes.append(drive_c)

        lutris_runners = home / ".local" / "share" / "lutris" / "runners" / "wine"
        if lutris_runners.is_dir():
            for prefix_dir in lutris_runners.iterdir():
                drive_c = prefix_dir / "drive_c"
                if drive_c.is_dir() and drive_c not in prefixes:
                    prefixes.append(drive_c)

        return prefixes
