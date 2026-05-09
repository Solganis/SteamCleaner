import os
import sys
import threading
import time
import tomllib

_hidden_hwnd = None
_saved_window_left = None
_saved_window_top = None

if sys.platform == "win32":
    try:
        _config_file = os.path.join(os.environ.get("APPDATA", ""), "steamcleaner", "config.toml")
        with open(_config_file, "rb") as _file:
            _config = tomllib.load(_file)
        _window_config = _config.get("window", {})
        if "left" in _window_config and "top" in _window_config:
            _saved_window_left = int(_window_config["left"])
            _saved_window_top = int(_window_config["top"])
    except (OSError, ValueError, KeyError):  # fmt: skip
        pass


def _hide_flutter_window():
    global _hidden_hwnd
    if sys.platform != "win32":
        return
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32  # noqa: E1101 -- windll is dynamically generated on Windows
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def find_flutter():
        result = [None]

        def enum_callback(handle, _):
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, buffer, 256)
            if "FLUTTER" in buffer.value.upper():
                result[0] = handle
                return False
            return True

        user32.EnumWindows(callback_type(enum_callback), 0)
        return result[0]

    for _ in range(5000):
        hwnd = find_flutter()
        if hwnd:
            target_left = _saved_window_left if _saved_window_left is not None else -32000
            target_top = _saved_window_top if _saved_window_top is not None else -32000
            user32.SetWindowPos(hwnd, 0, target_left, target_top, 0, 0, 0x0001 | 0x0004 | 0x0010)
            user32.ShowWindow(hwnd, 0)
            _hidden_hwnd = hwnd
            return
        time.sleep(0.001)


threading.Thread(target=_hide_flutter_window, daemon=True).start()

import flet as ft  # noqa: E402 -- must import after window-hiding thread starts

from steamcleaner.ui.gui.app import SteamCleanerGUI, _WindowHider  # noqa: E402 -- same reason as flet import above


async def main(page: ft.Page):
    hider = _WindowHider()
    hider._stop.set()
    hider._hwnd = _hidden_hwnd
    gui = SteamCleanerGUI(page, hider)
    await gui.initialize()


ft.run(main)
