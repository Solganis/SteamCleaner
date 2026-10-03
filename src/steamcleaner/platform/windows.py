import ctypes
import ctypes.wintypes
import logging
import os
import winreg
from pathlib import Path
from typing import ClassVar, Final

from steamcleaner.platform.base import FileAllocation, PlatformAdapter
from steamcleaner.platform.recycle_bin import forecast_keeps, recycle

_logger = logging.getLogger(__name__)

_FILE_READ_ATTRIBUTES: Final = 0x80
_FILE_SHARE_ALL: Final = 0x7
_OPEN_EXISTING: Final = 3
_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_STANDARD_INFO_CLASS: Final = 1
_INVALID_HANDLE: Final = ctypes.wintypes.HANDLE(-1).value
_EXTENDED_PREFIX: Final = "\\\\?\\"


class _FileStandardInfo(ctypes.Structure):
    _fields_ = (
        ("AllocationSize", ctypes.c_longlong),
        ("EndOfFile", ctypes.c_longlong),
        ("NumberOfLinks", ctypes.wintypes.DWORD),
        ("DeletePending", ctypes.wintypes.BOOLEAN),
        ("Directory", ctypes.wintypes.BOOLEAN),
    )


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = (
        ("dwFileAttributes", ctypes.wintypes.DWORD),
        ("ftCreationTime", ctypes.wintypes.FILETIME),
        ("ftLastAccessTime", ctypes.wintypes.FILETIME),
        ("ftLastWriteTime", ctypes.wintypes.FILETIME),
        ("dwVolumeSerialNumber", ctypes.wintypes.DWORD),
        ("nFileSizeHigh", ctypes.wintypes.DWORD),
        ("nFileSizeLow", ctypes.wintypes.DWORD),
        ("nNumberOfLinks", ctypes.wintypes.DWORD),
        ("nFileIndexHigh", ctypes.wintypes.DWORD),
        ("nFileIndexLow", ctypes.wintypes.DWORD),
    )


def _load_kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = ctypes.wintypes.HANDLE
    kernel32.GetFileInformationByHandleEx.argtypes = (
        ctypes.wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    )
    kernel32.GetFileInformationByHandleEx.restype = ctypes.wintypes.BOOL
    kernel32.GetFileInformationByHandle.argtypes = (ctypes.wintypes.HANDLE, ctypes.c_void_p)
    kernel32.GetFileInformationByHandle.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    kernel32.GetVolumePathNameW.argtypes = (ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPWSTR, ctypes.wintypes.DWORD)
    kernel32.GetVolumePathNameW.restype = ctypes.wintypes.BOOL
    kernel32.GetDiskFreeSpaceW.argtypes = (
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD,
    )
    kernel32.GetDiskFreeSpaceW.restype = ctypes.wintypes.BOOL
    return kernel32


_KERNEL32: Final = _load_kernel32()


def _extended_path(path: Path) -> str:
    """Return the `\\\\?\\` form of an absolute path, which lifts the 260-character limit."""
    absolute = os.path.abspath(path)
    if absolute.startswith(_EXTENDED_PREFIX):
        return absolute
    if absolute.startswith("\\\\"):
        return f"{_EXTENDED_PREFIX}UNC\\{absolute[2:]}"
    return f"{_EXTENDED_PREFIX}{absolute}"


def _query_cluster_bytes(extended_path: str) -> int:
    volume_root = ctypes.create_unicode_buffer(len(extended_path) + 1)
    sectors_per_cluster = ctypes.wintypes.DWORD()
    bytes_per_sector = ctypes.wintypes.DWORD()
    free_clusters = ctypes.wintypes.DWORD()
    total_clusters = ctypes.wintypes.DWORD()
    if not _KERNEL32.GetVolumePathNameW(
        extended_path, volume_root, len(volume_root)
    ) or not _KERNEL32.GetDiskFreeSpaceW(
        volume_root.value,
        ctypes.byref(sectors_per_cluster),
        ctypes.byref(bytes_per_sector),
        ctypes.byref(free_clusters),
        ctypes.byref(total_clusters),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return sectors_per_cluster.value * bytes_per_sector.value


class WindowsAdapter(PlatformAdapter):
    _HKEY_MAP: ClassVar[dict[str, int]] = {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
    }

    def __init__(self) -> None:
        self._cluster_bytes_by_volume: dict[int, int] = {}

    def keeps_trash(self, path: Path, size_bytes: int) -> bool:
        return forecast_keeps(path, size_bytes)

    def send_to_trash(self, path: Path) -> bool:
        return recycle(path)

    def file_allocation(self, path: Path) -> FileAllocation:
        """Return the clusters NTFS allocates to the file, after compression and sparse holes.

        An allocation that is not a whole number of clusters is reported as 0, a heuristic for a file stored in
        its MFT record. Measured on 4096-byte clusters: deleting 20000 such files gave back the same 2.9 MB at
        100 and at 600 bytes each.
        """
        extended_path = _extended_path(path)
        handle = _KERNEL32.CreateFileW(
            extended_path,
            _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_ALL,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if handle == _INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            standard = _FileStandardInfo()
            identity = _ByHandleFileInformation()
            if not _KERNEL32.GetFileInformationByHandleEx(
                handle, _FILE_STANDARD_INFO_CLASS, ctypes.byref(standard), ctypes.sizeof(standard)
            ) or not _KERNEL32.GetFileInformationByHandle(handle, ctypes.byref(identity)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _KERNEL32.CloseHandle(handle)
        volume = identity.dwVolumeSerialNumber
        if volume not in self._cluster_bytes_by_volume:
            self._cluster_bytes_by_volume[volume] = _query_cluster_bytes(extended_path)
        in_clusters = standard.AllocationSize % self._cluster_bytes_by_volume[volume] == 0
        return FileAllocation(
            allocated_bytes=standard.AllocationSize if in_clusters else 0,
            file_id=(volume, (identity.nFileIndexHigh << 32) | identity.nFileIndexLow),
            link_count=standard.NumberOfLinks,
        )

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

    def has_registry(self) -> bool:
        return True

    def read_registry_dword(self, key: str, subkey: str, value_name: str) -> int | None:
        hkey = self._HKEY_MAP.get(key)
        if hkey is None:
            return None
        try:
            with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as reg_key:
                value, value_type = winreg.QueryValueEx(reg_key, value_name)
        except OSError:
            return None
        return value if value_type == winreg.REG_DWORD else None

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
