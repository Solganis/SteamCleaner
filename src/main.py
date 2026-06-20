import logging
import sys
import threading
import time

from steamcleaner.utils.logging import setup_logging

_flutter_hwnd = None
_start_time = time.perf_counter()

setup_logging()
_logger = logging.getLogger("steamcleaner.main")


def _elapsed() -> str:
    return f"[{(time.perf_counter() - _start_time) * 1000:9.1f}ms]"


# ctypes attribute resolved at runtime; no type stubs
# noinspection PyUnresolvedReferences
def _find_flutter_window() -> None:
    global _flutter_hwnd
    if sys.platform != "win32":
        return
    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    # ctypes attribute resolved at runtime; no type stubs
    # noinspection PyUnresolvedReferences
    def find_flutter() -> int | None:
        result = [None]

        # ctypes attribute resolved at runtime; no type stubs
        # noinspection PyUnresolvedReferences
        def enum_callback(handle: int, _: int) -> bool:
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, buffer, 256)
            if "FLUTTER" in buffer.value.upper():
                result[0] = handle
                return False
            return True

        user32.EnumWindows(callback_type(enum_callback), 0)
        return result[0]

    _logger.debug("%s Thread started, searching for Flutter window", _elapsed())
    for iteration in range(5000):
        hwnd = find_flutter()
        if hwnd:
            _logger.debug(
                "%s Flutter window found (hwnd=%s, iteration=%s)",
                _elapsed(),
                hwnd,
                iteration,
            )
            _flutter_hwnd = hwnd
            return
        time.sleep(0.001)
    _logger.debug("%s Flutter window NOT found after 5000 iterations", _elapsed())


threading.Thread(target=_find_flutter_window, daemon=True).start()
_logger.debug("%s Thread launched, importing flet", _elapsed())

import flet as ft  # noqa: E402  # deferred until the window-finder thread starts (startup perf)

_logger.debug("%s Flet imported", _elapsed())

from steamcleaner.ui.gui.app import SteamCleanerGUI, WindowHider  # noqa: E402  # deferred, see flet import above

_logger.debug("%s App module imported, calling ft.run()", _elapsed())


async def main(page: ft.Page) -> None:
    _logger.debug("%s main() called by Flet", _elapsed())
    hider = WindowHider.from_hwnd(_flutter_hwnd)
    gui = SteamCleanerGUI(page, hider)
    await gui.initialize()


ft.run(main)
