import logging
import os
import winreg
from pathlib import Path

from steamcleaner.platform.base import PlatformAdapter

_logger = logging.getLogger(__name__)


class WindowsAdapter(PlatformAdapter):
    _HKEY_MAP = {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
    }

    def read_registry_str(self, key: str, subkey: str, value_name: str) -> str | None:
        hkey = self._HKEY_MAP.get(key)
        if hkey is None:
            _logger.debug("Unknown registry hive: %s", key)
            return None
        try:
            with winreg.OpenKey(hkey, subkey) as reg_key:
                value, _ = winreg.QueryValueEx(reg_key, value_name)
                result = str(value) if value else None
                _logger.debug("Registry %s\\%s@%s = %s", key, subkey, value_name, result)
                return result
        except OSError:
            _logger.debug("Registry key not found: %s\\%s@%s", key, subkey, value_name)
            return None

    def list_registry_subkeys(self, key: str, subkey: str) -> list[str]:
        hkey = self._HKEY_MAP.get(key)
        if hkey is None:
            return []
        try:
            with winreg.OpenKey(hkey, subkey) as reg_key:
                subkeys = []
                index = 0
                while True:
                    try:
                        subkeys.append(winreg.EnumKey(reg_key, index))
                        index += 1
                    except OSError:
                        break
                _logger.debug("Registry %s\\%s: %d subkeys", key, subkey, len(subkeys))
                return subkeys
        except OSError:
            _logger.debug("Registry key not found: %s\\%s", key, subkey)
            return []

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

    def programdata(self) -> Path:
        return Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
