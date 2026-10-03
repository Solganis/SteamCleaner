import ctypes
import ctypes.wintypes
import os
import shutil
import stat
import uuid
import winreg
from typing import TYPE_CHECKING, Final

from steamcleaner.platform.base import TrashRefusedError
from steamcleaner.utils.fs import dir_size, is_gone

if TYPE_CHECKING:
    from _ctypes import CFuncPtr
    from collections.abc import Callable
    from pathlib import Path

_E_NOINTERFACE: Final = ctypes.c_long(0x80004002).value
_E_ABORT: Final = ctypes.c_long(0x80004004).value
_RPC_E_CHANGED_MODE: Final = ctypes.c_long(0x80010106).value
_FACILITY_WIN32: Final = 0x8007
_CLSCTX_ALL: Final = 0x17
_APARTMENT_THREADED_NO_DDE: Final = 0x2 | 0x4
_SILENT_RECYCLE: Final = 0x0004 | 0x0010 | 0x0040 | 0x0400 | 0x00100000
_TSF_DELETE_RECYCLE_IF_POSSIBLE: Final = 0x80
_RELEASE: Final = 2
_SET_OPERATION_FLAGS: Final = 5
_DELETE_ITEM: Final = 18
_PERFORM_OPERATIONS: Final = 21
_GET_ANY_OPERATIONS_ABORTED: Final = 22
_PRE_DELETE_ITEM: Final = 11
_POST_DELETE_ITEM: Final = 12
_COMPARE: Final = 7
_SICHINT_CANONICAL: Final = 0x10000000
_FILE_SUPPORTS_HARD_LINKS: Final = 0x00400000
_MEGABYTE: Final = 1024 * 1024
_VOLUME_NAME_PREFIX: Final = "\\\\?\\Volume"
_VOLUME_NAME_CHARS: Final = 64
_BIN_SETTINGS: Final = "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\BitBucket\\Volume"
_EXPLORER_POLICIES: Final = "Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\Explorer"
_REFUSED: Final = "the Recycle Bin would not keep it"
_UNGUARDED: Final = "it cannot be held by a second name while the Recycle Bin takes it"


class _Guid(ctypes.Structure):
    _fields_ = (("data", ctypes.c_ubyte * 16),)


def _guid(text: str) -> _Guid:
    return _Guid.from_buffer_copy(uuid.UUID(text).bytes_le)


_CLSID_FILE_OPERATION: Final = _guid("3ad05575-8857-4850-9277-11b85bdb8e09")
_IID_FILE_OPERATION: Final = _guid("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
_IID_SHELL_ITEM: Final = _guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")
_SINK_INTERFACES: Final = (
    uuid.UUID("00000000-0000-0000-c000-000000000046").bytes_le,
    uuid.UUID("04b0f1a7-9490-44bc-96e1-4296a31252e2").bytes_le,
)

_HRESULT: Final = ctypes.c_long
_DWORD: Final = ctypes.wintypes.DWORD
_TEXT: Final = ctypes.wintypes.LPCWSTR
_INTERFACE: Final = ctypes.c_void_p
_TAKES_NOTHING: Final = ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE)
_TAKES_FLAGS: Final = ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD)
_TAKES_ITEM_AND_SINK: Final = ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _INTERFACE, _INTERFACE)
_GIVES_FLAG: Final = ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, ctypes.POINTER(ctypes.wintypes.BOOL))
_GIVES_ORDER: Final = ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _INTERFACE, _DWORD, ctypes.POINTER(ctypes.c_int))
_SINK_PROTOTYPES: Final = (
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, ctypes.POINTER(_Guid), ctypes.POINTER(_INTERFACE)),
    ctypes.WINFUNCTYPE(ctypes.wintypes.ULONG, _INTERFACE),
    ctypes.WINFUNCTYPE(ctypes.wintypes.ULONG, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _HRESULT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _TEXT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _TEXT, _HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _INTERFACE, _TEXT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _INTERFACE, _TEXT, _HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _INTERFACE, _TEXT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _INTERFACE, _TEXT, _HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _TEXT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, _DWORD, _INTERFACE, _TEXT, _TEXT, _DWORD, _HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE, ctypes.wintypes.UINT, ctypes.wintypes.UINT),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE),
    ctypes.WINFUNCTYPE(_HRESULT, _INTERFACE),
)


class _SinkMethods(ctypes.Structure):
    _fields_ = tuple((f"method_{slot}", prototype) for slot, prototype in enumerate(_SINK_PROTOTYPES))


class _Sink(ctypes.Structure):
    _fields_ = (("methods", ctypes.POINTER(_SinkMethods)),)


class _RecycleBinInfo(ctypes.Structure):
    _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1  # shellapi.h packs it to one byte on 32-bit only
    _fields_ = (
        ("cbSize", ctypes.wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    )


def _load_kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetVolumePathNameW.argtypes = (_TEXT, ctypes.wintypes.LPWSTR, _DWORD)
    kernel32.GetVolumePathNameW.restype = ctypes.wintypes.BOOL
    kernel32.GetVolumeNameForVolumeMountPointW.argtypes = (_TEXT, ctypes.wintypes.LPWSTR, _DWORD)
    kernel32.GetVolumeNameForVolumeMountPointW.restype = ctypes.wintypes.BOOL
    kernel32.GetVolumeInformationW.argtypes = (
        _TEXT,
        ctypes.wintypes.LPWSTR,
        _DWORD,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPDWORD,
        ctypes.wintypes.LPWSTR,
        _DWORD,
    )
    kernel32.GetVolumeInformationW.restype = ctypes.wintypes.BOOL
    return kernel32


def _load_shell32() -> ctypes.WinDLL:
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHQueryRecycleBinW.argtypes = (_TEXT, ctypes.POINTER(_RecycleBinInfo))
    shell32.SHQueryRecycleBinW.restype = _HRESULT
    shell32.SHCreateItemFromParsingName.argtypes = (
        _TEXT,
        _INTERFACE,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(_INTERFACE),
    )
    shell32.SHCreateItemFromParsingName.restype = _HRESULT
    return shell32


def _load_ole32() -> ctypes.WinDLL:
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, _DWORD)
    ole32.CoInitializeEx.restype = _HRESULT
    ole32.CoUninitialize.argtypes = ()
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = (
        ctypes.POINTER(_Guid),
        _INTERFACE,
        _DWORD,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(_INTERFACE),
    )
    ole32.CoCreateInstance.restype = _HRESULT
    return ole32


_KERNEL32: Final = _load_kernel32()
_SHELL32: Final = _load_shell32()
_OLE32: Final = _load_ole32()


def _accept(*_arguments: object) -> int:
    return 0


def _count_one(_this: int) -> int:
    return 1


class _DeleteWatcher:
    """The progress sink of one delete: refuses what the shell would not recycle, notes what became of the target."""

    def __init__(self, is_target: Callable[[int], bool]) -> None:
        self.refused = False
        self.result: int | None = None
        self.kept = False
        self._is_target = is_target
        handlers: list[Callable[..., int]] = [self._query_interface, _count_one, _count_one, *([_accept] * 16)]
        handlers[_PRE_DELETE_ITEM] = self._before_delete
        handlers[_POST_DELETE_ITEM] = self._after_delete
        self._callbacks = [prototype(handler) for prototype, handler in zip(_SINK_PROTOTYPES, handlers, strict=True)]
        self._methods = _SinkMethods(*self._callbacks)
        self.sink = _Sink(ctypes.pointer(self._methods))

    @staticmethod
    def _query_interface(this: int, interface_id: ctypes._Pointer[_Guid], out: ctypes._Pointer[ctypes.c_void_p]) -> int:
        if bytes(interface_id.contents.data) in _SINK_INTERFACES:
            out[0] = this
            return 0
        out[0] = None
        return _E_NOINTERFACE

    def _before_delete(self, _this: int, flags: int, _item: int) -> int:
        if flags & _TSF_DELETE_RECYCLE_IF_POSSIBLE:
            return 0
        self.refused = True
        return _E_ABORT

    def _after_delete(self, _this: int, _flags: int, item: int, result: int, recycled_item: int | None) -> int:
        if self._is_target(item):
            self.result = result
            self.kept = bool(recycled_item)
        return 0


def _method(interface: ctypes.c_void_p, slot: int, prototype: type[CFuncPtr]) -> CFuncPtr:
    methods = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return prototype(methods[slot])


def _is_same_item(announced: int, requested: ctypes.c_void_p) -> bool:
    order = ctypes.c_int(1)
    compared = _method(requested, _COMPARE, _GIVES_ORDER)(requested, announced, _SICHINT_CANONICAL, ctypes.byref(order))
    return compared == 0 and order.value == 0


def _shell_error(result: int) -> OSError:
    code = result & 0xFFFFFFFF
    if code >> 16 == _FACILITY_WIN32:
        return ctypes.WinError(code & 0xFFFF)
    return OSError(f"the shell could not move it to the Recycle Bin (0x{code:08X})")


def _check(result: int) -> None:
    if result < 0:
        raise _shell_error(result)


def _find_volume_root(path: Path) -> str | None:
    absolute = os.path.abspath(path)
    volume_root = ctypes.create_unicode_buffer(len(absolute) + 2)
    if not _KERNEL32.GetVolumePathNameW(absolute, volume_root, len(volume_root)):
        return None
    return volume_root.value


def _find_volume_id(volume_root: str) -> str | None:
    """Return the `{...}` identifier Windows keys a volume's settings by, or None for one that has none."""
    volume_name = ctypes.create_unicode_buffer(_VOLUME_NAME_CHARS)
    if not _KERNEL32.GetVolumeNameForVolumeMountPointW(volume_root, volume_name, len(volume_name)):
        return None
    return volume_name.value.removeprefix(_VOLUME_NAME_PREFIX).rstrip("\\")


def _measure_bin(volume_root: str) -> int | None:
    """Return the bytes the Recycle Bin of a volume holds, or None when the volume has no bin."""
    info = _RecycleBinInfo()
    info.cbSize = ctypes.sizeof(info)
    if _SHELL32.SHQueryRecycleBinW(volume_root, ctypes.byref(info)) != 0:
        return None
    return info.i64Size


def _read_number(hive: int, subkey: str, name: str) -> int | None:
    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None
    return value if isinstance(value, int) else None


def _is_ruled_by_policy() -> bool:
    """Whether a policy turns the bin off or sizes it. The size it sets is not read, so no room is known."""
    return any(
        _read_number(hive, _EXPLORER_POLICIES, "NoRecycleFiles") == 1
        or _read_number(hive, _EXPLORER_POLICIES, "RecycleBinSize") is not None
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    )


def _supports_hard_links(volume_root: str) -> bool:
    flags = ctypes.wintypes.DWORD()
    known = _KERNEL32.GetVolumeInformationW(volume_root, None, 0, None, None, ctypes.byref(flags), None, 0)
    return bool(known and flags.value & _FILE_SUPPORTS_HARD_LINKS)


def find_room(path: Path) -> int | None:
    """Return the bytes the Recycle Bin of path's volume takes beside what it holds. None: it keeps nothing.

    Measured: an item up to `MaxCapacity` megabytes is recycled whatever the bin holds, and a bin grown past
    that size drops its oldest items within seconds. The size is read from the registry, not from the
    shell. A bin nobody sized is taken at 5% of the volume, a guess on the low side: 10% was seen on two
    small volumes. A setting that is there and cannot be read means no room is known.
    """
    volume_root = _find_volume_root(path)
    try:
        return None if volume_root is None else _read_room(volume_root)
    except OSError:
        return None


def _read_room(volume_root: str) -> int | None:
    held = None if _is_ruled_by_policy() else _measure_bin(volume_root)
    if held is None:
        return None
    volume_id = _find_volume_id(volume_root)
    settings = f"{_BIN_SETTINGS}\\{volume_id}"
    if volume_id and _read_number(winreg.HKEY_CURRENT_USER, settings, "NukeOnDelete") == 1:
        return None
    megabytes = _read_number(winreg.HKEY_CURRENT_USER, settings, "MaxCapacity") if volume_id else None
    if megabytes is not None:
        return max(megabytes * _MEGABYTE - held, 0)
    return max(shutil.disk_usage(volume_root).total // 20 - held, 0)


def _read_outcome(watcher: _DeleteWatcher, performed: int, *, aborted: bool) -> bool:
    """Return whether the bin holds the target. Raise unless its own delete succeeded."""
    if watcher.refused:
        raise TrashRefusedError(_REFUSED)
    _check(performed)
    if aborted or watcher.result is None:
        raise OSError("the shell did not move it to the Recycle Bin")
    _check(watcher.result)
    return watcher.kept


def _is_same_file(path: Path, other: Path) -> bool:
    try:
        return os.path.samefile(path, other)
    except OSError:
        return False


def forecast_keeps(path: Path, size_bytes: int) -> bool:
    """Forecast whether recycle would move an item of this size at path to the bin. recycle decides."""
    room = find_room(path)
    if room is None or size_bytes > room:
        return False
    volume_root = _find_volume_root(path)
    return os.path.isdir(path) or (volume_root is not None and _supports_hard_links(volume_root))


def _delete_through_shell(path: Path) -> bool:
    operation = ctypes.c_void_p()
    item = ctypes.c_void_p()
    watcher = _DeleteWatcher(lambda announced: _is_same_item(announced, item))
    aborted = ctypes.wintypes.BOOL()
    try:
        _check(
            _OLE32.CoCreateInstance(
                ctypes.byref(_CLSID_FILE_OPERATION),
                None,
                _CLSCTX_ALL,
                ctypes.byref(_IID_FILE_OPERATION),
                ctypes.byref(operation),
            )
        )
        _check(
            _SHELL32.SHCreateItemFromParsingName(
                os.path.abspath(path), None, ctypes.byref(_IID_SHELL_ITEM), ctypes.byref(item)
            )
        )
        _check(_method(operation, _SET_OPERATION_FLAGS, _TAKES_FLAGS)(operation, _SILENT_RECYCLE))
        _check(_method(operation, _DELETE_ITEM, _TAKES_ITEM_AND_SINK)(operation, item, ctypes.addressof(watcher.sink)))
        performed = _method(operation, _PERFORM_OPERATIONS, _TAKES_NOTHING)(operation)
        _check(_method(operation, _GET_ANY_OPERATIONS_ABORTED, _GIVES_FLAG)(operation, ctypes.byref(aborted)))
    finally:
        for interface in (item, operation):
            if interface:
                _method(interface, _RELEASE, _TAKES_NOTHING)(interface)
    return _read_outcome(watcher, performed, aborted=bool(aborted.value))


def _settle_second_name(path: Path, guard: Path, *, kept: bool, names: int) -> bool:
    """Drop the second name where the file is safe without it, else give the file its name back.

    Return whether the bin holds the file: the shell said so and the file still has the names it had, which
    another file recycled in its place would not leave it. The name is given back by a rename that refuses
    an existing destination.
    """
    if _is_same_file(path, guard):
        guard.unlink()
        return False
    if kept and guard.stat().st_nlink >= names:
        guard.unlink()
        return True
    try:
        os.rename(guard, path)
    except FileExistsError:
        raise OSError(f"another file took its name, the file itself is kept as {guard.name}") from None
    return False


def _recycle_file(path: Path) -> bool:
    guard = path.with_name(f"{path.name}.{uuid.uuid4().hex}.steamcleaner")
    try:
        os.link(path, guard)
    except OSError as error:
        raise TrashRefusedError(_UNGUARDED) from error
    names = guard.stat().st_nlink
    if not _is_same_file(path, guard):
        raise OSError(f"another file took its name, the file itself is kept as {guard.name}")
    kept = False
    try:
        kept = _delete_through_shell(path)
    finally:
        in_the_bin = _settle_second_name(path, guard, kept=kept, names=names)
    if not in_the_bin:
        raise TrashRefusedError(_REFUSED)
    return True


def recycle(path: Path) -> bool:
    """Move path to the Recycle Bin and return whether the bin holds it. False only for a folder that is gone.

    Refused before the shell is asked: what the bin has no room for beside what it holds, since it would
    drop its oldest items for it. The shell is then asked before each item and stopped where it would
    delete for good. It does not say so for a single file larger than the bin (measured), so a file gets
    a second name first: if the shell deletes it for good after all, that name is renamed back.

    Raises:
        TrashRefusedError: The bin would not keep it, or the volume has no hard links to hold a file by.
            Nothing was deleted for good.
        OSError: The shell could not move it.
    """
    path_stat = path.lstat()
    is_folder = stat.S_ISDIR(path_stat.st_mode)
    room = find_room(path)
    if room is None or (dir_size(path) if is_folder else path_stat.st_size) > room:
        raise TrashRefusedError(_REFUSED)
    started = _OLE32.CoInitializeEx(None, _APARTMENT_THREADED_NO_DDE)
    if started < 0 and started != _RPC_E_CHANGED_MODE:
        raise _shell_error(started)
    try:
        if not is_folder:
            return _recycle_file(path)
        kept = _delete_through_shell(path)
        if not kept and not is_gone(path):
            raise OSError("the shell left it where it was")
        return kept
    finally:
        if started >= 0:
            _OLE32.CoUninitialize()
