from __future__ import annotations

import os
from pathlib import Path

from steamcleaner.platform.base import PlatformAdapter


class LinuxAdapter(PlatformAdapter):
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        return None

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
