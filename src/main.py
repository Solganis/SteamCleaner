import os
import sys
import threading
import time
import tomllib

_hidden_hwnd = None
_saved_window_left = None
_saved_window_top = None
_t0 = time.perf_counter()
_log_path = os.path.join(os.environ.get("APPDATA", ""), "steamcleaner", "startup_debug.log")
_log_lines: list[str] = []


def _log(message: str):
    elapsed = (time.perf_counter() - _t0) * 1000
    _log_lines.append(f"[{elapsed:8.1f}ms] {message}")


_log("Python started")

if sys.platform == "win32":
    try:
        _config_file = os.path.join(os.environ.get("APPDATA", ""), "steamcleaner", "config.toml")
        with open(_config_file, "rb") as _file:
            _config = tomllib.load(_file)
        _window_config = _config.get("window", {})
        if "left" in _window_config and "top" in _window_config:
            _saved_window_left = int(_window_config["left"])
            _saved_window_top = int(_window_config["top"])
            _log(f"Config loaded: left={_saved_window_left}, top={_saved_window_top}")
        else:
            _log("Config found but no window position saved")
    except (OSError, ValueError, KeyError) as exc:
        _log(f"Config read failed: {exc}")


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

    _log("Thread started, searching for Flutter window")
    for iteration in range(5000):
        hwnd = find_flutter()
        if hwnd:
            _log(f"Flutter window found: hwnd={hwnd}, iteration={iteration}")

            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            _log(f"Window rect BEFORE: left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}")

            is_visible = user32.IsWindowVisible(hwnd)
            _log(f"Window visible BEFORE: {bool(is_visible)}")

            target_left = _saved_window_left if _saved_window_left is not None else -32000
            target_top = _saved_window_top if _saved_window_top is not None else -32000

            result_pos = user32.SetWindowPos(hwnd, 0, target_left, target_top, 0, 0, 0x0001 | 0x0004 | 0x0010)
            _log(f"SetWindowPos({target_left}, {target_top}) returned: {result_pos}")

            result_hide = user32.ShowWindow(hwnd, 0)
            _log(f"ShowWindow(SW_HIDE) returned: {result_hide}")

            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            is_visible = user32.IsWindowVisible(hwnd)
            _log(f"Window rect AFTER: left={rect.left}, top={rect.top}, right={rect.right}, bottom={rect.bottom}")
            _log(f"Window visible AFTER: {bool(is_visible)}")

            _hidden_hwnd = hwnd

            try:
                os.makedirs(os.path.dirname(_log_path), exist_ok=True)
                with open(_log_path, "w", encoding="utf-8") as log_file:
                    log_file.write("\n".join(_log_lines) + "\n")
            except OSError:
                pass
            return
        time.sleep(0.001)

    _log("Flutter window NOT FOUND after 5000 iterations")
    try:
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, "w", encoding="utf-8") as log_file:
            log_file.write("\n".join(_log_lines) + "\n")
    except OSError:
        pass


threading.Thread(target=_hide_flutter_window, daemon=True).start()
_log("Thread launched, importing flet")

import flet as ft  # noqa: E402 -- must import after window-hiding thread starts

_log("Flet imported")

from steamcleaner.ui.gui.app import SteamCleanerGUI, _WindowHider  # noqa: E402 -- same reason as flet import above

_log("App module imported, calling ft.run()")


async def main(page: ft.Page):
    _log("main() called by Flet")
    try:
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, "w", encoding="utf-8") as log_file:
            log_file.write("\n".join(_log_lines) + "\n")
    except OSError:
        pass

    hider = _WindowHider()
    hider._stop.set()
    hider._hwnd = _hidden_hwnd
    gui = SteamCleanerGUI(page, hider)
    await gui.initialize()


ft.run(main)
