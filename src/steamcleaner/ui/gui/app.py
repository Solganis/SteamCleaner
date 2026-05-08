from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time

import darkdetect
import flet as ft

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.config import get_value, save_value
from steamcleaner.utils.fs import format_size


class _WindowHider:
    """Hides the Flutter window before Python gets control via WebSocket.

    Flet's Flutter runtime creates and shows a native window before any
    Python code runs. This class polls for the Flutter window class at 1ms
    intervals and immediately moves it off-screen + hides it, preventing
    the visible "jump" when restoring saved window geometry.

    Windows-only. On other platforms this is a no-op.
    """

    def __init__(self):
        self._hwnd: int | None = None
        self._stop = threading.Event()

    def start(self):
        if sys.platform != "win32":
            return
        thread = threading.Thread(target=self._monitor, daemon=True)
        thread.start()

    def stop(self):
        self._stop.set()

    def show(self):
        if self._hwnd is None:
            return
        import ctypes

        ctypes.windll.user32.ShowWindow(self._hwnd, 5)  # SW_SHOW

    def _monitor(self):
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        sw_hide = 0
        swp_nosize = 0x0001
        swp_nozorder = 0x0004
        swp_noactivate = 0x0010

        enum_callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        def find_flutter():
            found = [None]

            def callback(hwnd, _):
                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, 256)
                if "FLUTTER" in class_name.value.upper():
                    found[0] = hwnd
                    return False
                return True

            user32.EnumWindows(enum_callback_type(callback), 0)
            return found[0]

        while not self._stop.is_set():
            hwnd = find_flutter()
            if hwnd:
                user32.SetWindowPos(hwnd, 0, -32000, -32000, 0, 0, swp_nosize | swp_nozorder | swp_noactivate)
                user32.ShowWindow(hwnd, sw_hide)
                self._hwnd = hwnd
                return
            time.sleep(0.001)


class SteamCleanerGUI:
    def __init__(self, page: ft.Page, window_hider: _WindowHider | None = None):
        self._page = page
        self._result = ScanResult()
        self._selected: set[int] = set()
        self._cancel_event: threading.Event | None = None
        self._window_hider = window_hider or _WindowHider()
        self._status = ft.Text("Ready")
        self._total_label = ft.Text("")
        self._theme_button = ft.IconButton()
        self._scan_button = ft.Button("Scan")
        self._clean_button = ft.Button("Clean Selected", disabled=True)
        self._select_all_button = ft.TextButton("Select All", disabled=True)
        self._progress = ft.ProgressBar(visible=False)
        self._results_list = ft.ListView()
        self._setup_page()

    async def initialize(self):
        self._window_hider.stop()
        self._page.update()
        await asyncio.sleep(0.15)
        self._build_ui()

    def _setup_page(self):
        self._page.title = "SteamCleaner"
        saved_theme = get_value("ui", "theme")
        match saved_theme:
            case "light":
                self._page.theme_mode = ft.ThemeMode.LIGHT
            case "dark":
                self._page.theme_mode = ft.ThemeMode.DARK
            case _:
                os_theme = darkdetect.theme()
                if os_theme == "Light":
                    self._page.theme_mode = ft.ThemeMode.LIGHT
                else:
                    self._page.theme_mode = ft.ThemeMode.DARK
        self._page.theme = ft.Theme(
            color_scheme_seed=ft.Colors.BLUE,
            visual_density=ft.VisualDensity.COMPACT,
        )
        self._page.window.width = int(get_value("window", "width") or "960")
        self._page.window.height = int(get_value("window", "height") or "640")
        self._page.window.min_width = 720
        self._page.window.min_height = 480
        saved_left = get_value("window", "left")
        saved_top = get_value("window", "top")
        if saved_left is not None and saved_top is not None:
            self._page.window.left = int(saved_left)
            self._page.window.top = int(saved_top)
        self._page.window.on_event = self._on_window_event
        self._page.padding = 0

    def _save_window_geometry(self):
        window = self._page.window
        if window.width is None or window.height is None or window.left is None or window.top is None:
            return
        save_value("window", "width", str(int(window.width)))
        save_value("window", "height", str(int(window.height)))
        save_value("window", "left", str(int(window.left)))
        save_value("window", "top", str(int(window.top)))

    def _on_window_event(self, event: ft.WindowEvent):
        match event.type:
            case ft.WindowEventType.RESIZED | ft.WindowEventType.MOVED:
                self._save_window_geometry()

    def _build_ui(self):
        self._status = ft.Text("Ready", size=14)
        self._total_label = ft.Text("", size=14, weight=ft.FontWeight.BOLD)

        is_dark = self._page.theme_mode == ft.ThemeMode.DARK
        self._theme_button = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE,
            tooltip="Switch to light theme" if is_dark else "Switch to dark theme",
            on_click=self._on_toggle_theme,
        )

        self._scan_button = ft.Button(
            "Scan",
            icon=ft.Icons.SEARCH,
            on_click=self._on_scan,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )
        self._clean_button = ft.Button(
            "Clean Selected",
            icon=ft.Icons.DELETE_SWEEP,
            on_click=self._on_clean,
            disabled=True,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                color={
                    ft.ControlState.DEFAULT: ft.Colors.WHITE,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.4, ft.Colors.WHITE),
                },
                bgcolor={
                    ft.ControlState.DEFAULT: ft.Colors.RED_700,
                    ft.ControlState.HOVERED: ft.Colors.RED_800,
                    ft.ControlState.DISABLED: ft.Colors.with_opacity(0.3, ft.Colors.RED_700),
                },
            ),
        )
        self._select_all_button = ft.TextButton(
            "Select All",
            on_click=self._on_select_all,
            disabled=True,
        )

        self._progress = ft.ProgressBar(visible=False)

        self._results_list = ft.ListView(expand=True, spacing=2, padding=ft.Padding.symmetric(horizontal=16))

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=28, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=22, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    self._status,
                    self._theme_button,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=12),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
        )

        toolbar = ft.Container(
            content=ft.Row(
                [
                    self._scan_button,
                    self._select_all_button,
                    ft.Container(expand=True),
                    self._total_label,
                    self._clean_button,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
        )

        self._page.add(
            header,
            self._progress,
            toolbar,
            ft.Divider(height=1),
            ft.Container(content=self._results_list, expand=True),
        )
        self._window_hider.show()
        self._page.window.visible = True
        self._page.update()

    def _make_row(self, index: int, entry: JunkEntry) -> ft.Container:
        checkbox = ft.Checkbox(
            value=index in self._selected,
            on_change=lambda event, idx=index: self._on_toggle(idx, event.control.value),
        )

        category_colors = {
            "redistributable": ft.Colors.ORANGE_700,
            "shader_cache": ft.Colors.PURPLE_700,
            "crash_dump": ft.Colors.RED_700,
            "old_log": ft.Colors.BLUE_GREY_700,
            "installer": ft.Colors.AMBER_700,
            "cross_platform": ft.Colors.TEAL_700,
        }

        badge = ft.Container(
            content=ft.Text(entry.category.value.replace("_", " "), size=11, color=ft.Colors.WHITE),
            bgcolor=category_colors.get(entry.category.value, ft.Colors.GREY_700),
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

        return ft.Container(
            content=ft.Row(
                [
                    checkbox,
                    ft.Text(
                        format_size(entry.size_bytes),
                        width=80,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_500,
                    ),
                    badge,
                    ft.Text(
                        str(entry.path),
                        expand=True,
                        size=13,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        tooltip=str(entry.path),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=4, vertical=2),
            border_radius=6,
            ink=True,
            on_click=lambda event, idx=index: self._on_row_click(idx),
        )

    def _refresh_list(self):
        self._results_list.controls.clear()
        for entry_index, entry in enumerate(self._result.entries):
            self._results_list.controls.append(self._make_row(entry_index, entry))
        self._update_totals()
        self._page.update()

    def _update_totals(self):
        selected_bytes = sum(self._result.entries[entry_index].size_bytes for entry_index in self._selected)
        total_formatted = format_size(self._result.total_bytes)
        selected_formatted = format_size(selected_bytes)
        self._total_label.value = (
            f"{selected_formatted} / {total_formatted} selected ({len(self._selected)}/{len(self._result.entries)})"
        )
        has_selection = len(self._selected) > 0
        self._clean_button.disabled = not has_selection
        self._select_all_button.disabled = len(self._result.entries) == 0

    def _on_toggle(self, index: int, checked: bool):
        if checked:
            self._selected.add(index)
        else:
            self._selected.discard(index)
        self._update_totals()
        self._page.update()

    def _on_row_click(self, index: int):
        if index in self._selected:
            self._selected.discard(index)
        else:
            self._selected.add(index)
        self._refresh_list()

    def _on_select_all(self, _event):
        if len(self._selected) == len(self._result.entries):
            self._selected.clear()
            self._select_all_button.text = "Select All"
        else:
            self._selected = set(range(len(self._result.entries)))
            self._select_all_button.text = "Deselect All"
        self._refresh_list()

    def _on_toggle_theme(self, _event):
        if self._page.theme_mode == ft.ThemeMode.DARK:
            self._page.theme_mode = ft.ThemeMode.LIGHT
            self._theme_button.icon = ft.Icons.DARK_MODE
            self._theme_button.tooltip = "Switch to dark theme"
            save_value("ui", "theme", "light")
        else:
            self._page.theme_mode = ft.ThemeMode.DARK
            self._theme_button.icon = ft.Icons.LIGHT_MODE
            self._theme_button.tooltip = "Switch to light theme"
            save_value("ui", "theme", "dark")
        self._page.update()

    def _reset_scan_ui(self):
        self._scan_button.text = "Scan"
        self._scan_button.icon = ft.Icons.SEARCH
        self._progress.visible = False
        self._cancel_event = None

    def _set_controls_locked(self, locked: bool):
        self._clean_button.disabled = locked or not self._selected
        self._select_all_button.disabled = locked or len(self._result.entries) == 0
        self._results_list.disabled = locked

    def _on_scan(self, _event):
        if self._cancel_event is not None:
            self._cancel_event.set()
            return

        self._cancel_event = threading.Event()
        self._scan_button.text = "Stop"
        self._scan_button.icon = ft.Icons.STOP
        self._progress.visible = True
        self._status.value = "Scanning..."
        self._result = ScanResult()
        self._selected.clear()
        self._results_list.controls.clear()
        self._total_label.value = ""
        self._set_controls_locked(locked=True)
        self._page.update()
        self._page.run_task(self._scan_task)

    async def _scan_task(self):
        cancel = self._cancel_event
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        status_text = ["Scanning..."]
        scan_done = threading.Event()

        def on_progress(message: str, _count: int):
            if not cancel.is_set():
                status_text[0] = message

        def on_found(entry: JunkEntry):
            if not cancel.is_set():
                found_queue.put(entry)

        def run_scan():
            try:
                from steamcleaner.platform import create_adapter

                platform = create_adapter()
                exclusions = ExclusionRegistry()
                engine = ScanEngine(platform, exclusions)
                engine.scan(progress=on_progress, on_found=on_found, cancel=cancel)
            except Exception:
                status_text[0] = "Scan failed"
            finally:
                scan_done.set()

        threading.Thread(target=run_scan, daemon=True).start()

        while not scan_done.is_set():
            self._drain_found_queue(found_queue)
            self._status.value = status_text[0]
            self._page.update()
            await asyncio.sleep(0.15)

        self._drain_found_queue(found_queue)

        entry_count = len(self._result.entries)
        if cancel.is_set():
            self._status.value = f"Stopped: {entry_count} items found so far"
        elif status_text[0] == "Scan failed":
            self._status.value = "Scan failed"
        else:
            self._status.value = f"Found {entry_count} items: {format_size(self._result.total_bytes)}"

        self._reset_scan_ui()
        self._set_controls_locked(locked=False)
        self._update_totals()
        self._page.update()

    def _drain_found_queue(self, found_queue: queue.Queue[JunkEntry]):
        while not found_queue.empty():
            entry = found_queue.get_nowait()
            entry_index = len(self._result.entries)
            self._result.entries.append(entry)
            self._results_list.controls.append(self._make_row(entry_index, entry))
            self._total_label.value = f"{len(self._result.entries)} items, {format_size(self._result.total_bytes)}"

    def _on_clean(self, _event):
        if not self._selected:
            return

        entries = [self._result.entries[entry_index] for entry_index in sorted(self._selected)]
        selected_bytes = sum(entry.size_bytes for entry in entries)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm deletion"),
            content=ft.Text(f"Move {len(entries)} items ({format_size(selected_bytes)}) to trash?"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dialog)),
                ft.Button(
                    "Delete",
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.RED_700,
                    on_click=lambda _: self._confirm_clean(dialog, entries),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._page.show_dialog(dialog)

    def _close_dialog(self, dialog: ft.AlertDialog):
        self._page.pop_dialog()

    def _confirm_clean(self, dialog: ft.AlertDialog, entries: list[JunkEntry]):
        self._page.pop_dialog()
        self._status.value = "Cleaning..."
        self._progress.visible = True
        self._set_controls_locked(locked=True)
        self._scan_button.disabled = True
        self._page.update()

        deleted_set = set(id(entry) for entry in entries)

        def do_clean():
            selected_result = ScanResult(entries=entries)
            cleaner = CleanEngine(use_trash=True, dry_run=False)
            stats = cleaner.clean(selected_result)

            self._result.entries = [entry for entry in self._result.entries if id(entry) not in deleted_set]
            self._selected.clear()

            self._scan_button.disabled = False
            self._progress.visible = False

            entry_count = len(self._result.entries)
            if stats.errors:
                error_summary = f"Deleted {stats.deleted}, failed {stats.skipped}: {stats.errors[0]}"
                self._show_snackbar(error_summary)
                self._status.value = f"{entry_count} items remaining, {stats.skipped} failed"
            else:
                self._show_snackbar(f"Deleted {stats.deleted} items ({format_size(stats.bytes_freed)})")
                self._status.value = f"{entry_count} items remaining"

            self._set_controls_locked(locked=False)
            self._refresh_list()

        threading.Thread(target=do_clean, daemon=True).start()

    def _show_snackbar(self, message: str):
        snackbar = ft.SnackBar(content=ft.Text(message), duration=4000, open=True)
        self._page.overlay.append(snackbar)
        self._page.update()


def run_gui():
    hider = _WindowHider()
    hider.start()

    async def main(page: ft.Page):
        gui = SteamCleanerGUI(page, hider)
        await gui.initialize()

    ft.run(main)
