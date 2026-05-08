from __future__ import annotations

import os
import winreg
from pathlib import Path

from steamcleaner.platform.base import PlatformAdapter


class WindowsAdapter(PlatformAdapter):
    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        hkey_map = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
        }
        hkey = hkey_map.get(key)
        if hkey is None:
            return None
        try:
            with winreg.OpenKey(hkey, subkey) as reg_key:
                value, _ = winreg.QueryValueEx(reg_key, value_name)
                return str(value) if value else None
        except OSError:
            return None

    def appdata_local(self) -> Path:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))

    def appdata_roaming(self) -> Path:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))

    def home(self) -> Path:
        return Path.home()

    def program_files(self) -> list[Path]:
        paths = []
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            env_value = os.environ.get(var)
            if env_value:
                program_path = Path(env_value)
                if program_path.is_dir() and program_path not in paths:
                    paths.append(program_path)
        return paths
