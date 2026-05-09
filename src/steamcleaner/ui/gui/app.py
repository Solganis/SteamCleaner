from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
from pathlib import Path

import darkdetect
import flet as ft

from steamcleaner.cleaner.engine import CleanEngine, CleanStats
from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.config import get_value, save_value
from steamcleaner.utils.fs import format_size

_VERSION = "0.2.0"
_GITHUB_URL = "https://github.com/Solganis/SteamCleaner"
_BOOSTY_URL = "https://boosty.to/solganis"


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
        self._selected: set[Path] = set()
        self._visible_entries: list[JunkEntry] = []
        self._sort_key = "size_desc"
        self._category_filter: str | None = None
        self._search_query = ""
        self._cancel_event: threading.Event | None = None
        self._text_input_focused = False
        self._window_hider = window_hider or _WindowHider()
        self._status = ft.Text("Ready")
        self._total_label = ft.Text("")
        self._theme_button = ft.IconButton()
        self._scan_button = ft.Button("Scan")
        self._clean_button = ft.Button("Clean Selected", disabled=True)
        self._select_all_button = ft.TextButton("Select All", disabled=True)
        self._sort_dropdown = ft.Dropdown(width=160)
        self._filter_dropdown = ft.Dropdown(width=160)
        self._search_field = ft.TextField()
        self._progress = ft.ProgressBar(visible=False)
        self._results_list = ft.ListView()
        self._empty_state = ft.Column()
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
        self._page.on_keyboard_event = self._on_keyboard
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

    def _set_text_input_focus(self, focused: bool):
        self._text_input_focused = focused

    def _on_keyboard(self, event: ft.KeyboardEvent):
        if event.key == "Escape":
            if self._cancel_event is not None:
                self._cancel_event.set()
            elif self._selected:
                self._selected.clear()
                self._select_all_button.text = "Select All"
                self._refresh_list()
            elif self._text_input_focused:
                self._search_field.value = ""
                self._search_query = ""
                self._page.focus()
                self._refresh_list()
            return

        if self._text_input_focused:
            return

        if event.key == "A" and event.ctrl:
            self._on_select_all(None)
        elif event.key == "Delete" and self._selected and self._cancel_event is None:
            self._on_clean(None)

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

        self._sort_dropdown = ft.Dropdown(
            width=200,
            value="size_desc",
            label="Sort by",
            options=[
                ft.dropdown.Option("size_desc", "Size (largest)"),
                ft.dropdown.Option("size_asc", "Size (smallest)"),
                ft.dropdown.Option("category", "Category"),
                ft.dropdown.Option("path", "Path"),
            ],
            on_select=self._on_sort_changed,
            dense=True,
            text_size=13,
        )

        self._filter_dropdown = ft.Dropdown(
            width=200,
            value="all",
            label="Filter",
            options=[ft.dropdown.Option("all", "All categories")],
            on_select=self._on_filter_changed,
            dense=True,
            text_size=13,
        )

        self._search_field = ft.TextField(
            label="Search",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            dense=True,
            text_size=13,
            on_change=self._on_search_changed,
            on_focus=lambda _: self._set_text_input_focus(True),
            on_blur=lambda _: self._set_text_input_focus(False),
        )

        self._progress = ft.ProgressBar(visible=False)

        self._results_list = ft.ListView(expand=True, spacing=2, padding=ft.Padding.symmetric(horizontal=16))

        settings_button = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            tooltip="Settings",
            on_click=self._on_settings_click,
        )
        about_button = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINE,
            tooltip="About",
            on_click=self._on_about_click,
        )

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=28, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=22, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    self._status,
                    settings_button,
                    about_button,
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
                    self._sort_dropdown,
                    self._filter_dropdown,
                    self._search_field,
                    self._total_label,
                    self._clean_button,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
        )

        self._empty_state = ft.Column(
            [
                ft.Container(expand=True),
                ft.Icon(ft.Icons.SEARCH_OFF, size=48, color=ft.Colors.with_opacity(0.4, ft.Colors.ON_SURFACE)),
                ft.Text(
                    "Click Scan to find junk files",
                    size=16,
                    color=ft.Colors.with_opacity(0.5, ft.Colors.ON_SURFACE),
                ),
                ft.Container(expand=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            expand=True,
        )

        self._page.add(
            header,
            self._progress,
            toolbar,
            ft.Divider(height=1),
            ft.Stack([self._results_list, self._empty_state], expand=True),
        )
        self._window_hider.show()
        self._page.window.visible = True
        self._page.update()

    _CATEGORY_COLORS = {
        "redistributable": ft.Colors.ORANGE_700,
        "shader_cache": ft.Colors.PURPLE_700,
        "crash_dump": ft.Colors.RED_700,
        "old_log": ft.Colors.BLUE_GREY_700,
        "installer": ft.Colors.AMBER_700,
        "cross_platform": ft.Colors.TEAL_700,
    }

    def _make_row(self, entry: JunkEntry) -> ft.Container:
        entry_path = entry.path
        checkbox = ft.Checkbox(
            value=entry_path in self._selected,
            on_change=lambda event, path=entry_path: self._on_toggle(path, event.control.value),
        )

        badge = ft.Container(
            content=ft.Text(entry.category.value.replace("_", " "), size=11, color=ft.Colors.WHITE),
            bgcolor=self._CATEGORY_COLORS.get(entry.category.value, ft.Colors.GREY_700),
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

        actions_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            icon_size=16,
            padding=0,
            items=[
                ft.PopupMenuItem(
                    "Open in Explorer",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda _, path=entry_path: self._open_in_explorer(path),
                ),
                ft.PopupMenuItem(
                    "Copy path",
                    icon=ft.Icons.CONTENT_COPY,
                    on_click=lambda _, path=entry_path: self._copy_path(path),
                ),
            ],
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
                    actions_menu,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            padding=ft.Padding.symmetric(horizontal=4, vertical=2),
            border_radius=6,
            ink=True,
            on_click=lambda event, path=entry_path: self._on_row_click(path),
        )

    def _apply_sort_filter(self):
        entries = self._result.entries
        if self._category_filter and self._category_filter != "all":
            entries = [entry for entry in entries if entry.category.value == self._category_filter]
        if self._search_query:
            query = self._search_query.lower()
            entries = [entry for entry in entries if query in str(entry.path).lower()]
        match self._sort_key:
            case "size_desc":
                entries = sorted(entries, key=lambda entry: entry.size_bytes, reverse=True)
            case "size_asc":
                entries = sorted(entries, key=lambda entry: entry.size_bytes)
            case "category":
                entries = sorted(entries, key=lambda entry: entry.category.value)
            case "path":
                entries = sorted(entries, key=lambda entry: str(entry.path).lower())
        self._visible_entries = entries

    def _refresh_list(self):
        self._apply_sort_filter()
        self._results_list.controls.clear()
        for entry in self._visible_entries:
            self._results_list.controls.append(self._make_row(entry))
        self._update_empty_state()
        self._update_totals()
        self._page.update()

    def _update_empty_state(self):
        has_results = len(self._result.entries) > 0
        has_visible = len(self._visible_entries) > 0
        icon_control = self._empty_state.controls[1]
        text_control = self._empty_state.controls[2]
        assert isinstance(icon_control, ft.Icon)
        assert isinstance(text_control, ft.Text)

        if has_visible:
            self._empty_state.visible = False
        elif has_results:
            icon_control.name = ft.Icons.FILTER_LIST_OFF
            text_control.value = "No results matching your filters"
            self._empty_state.visible = True
        else:
            icon_control.name = ft.Icons.SEARCH_OFF
            text_control.value = "Click Scan to find junk files"
            self._empty_state.visible = True

    def _rebuild_filter_options(self):
        categories = sorted({entry.category.value for entry in self._result.entries})
        options: list[ft.dropdown.Option] = [ft.dropdown.Option("all", "All categories")]
        for category in categories:
            label = category.replace("_", " ").title()
            options.append(ft.dropdown.Option(category, label))
        self._filter_dropdown.options = options
        if self._category_filter not in categories:
            self._category_filter = None
            self._filter_dropdown.value = "all"

    def _update_totals(self):
        selected_bytes = sum(entry.size_bytes for entry in self._result.entries if entry.path in self._selected)
        total_formatted = format_size(self._result.total_bytes)
        selected_formatted = format_size(selected_bytes)
        visible_count = len(self._visible_entries)
        total_count = len(self._result.entries)
        filter_note = f" ({visible_count} shown)" if visible_count != total_count else ""
        self._total_label.value = (
            f"{selected_formatted} / {total_formatted} selected ({len(self._selected)}/{total_count}){filter_note}"
        )
        has_selection = len(self._selected) > 0
        self._clean_button.disabled = not has_selection
        self._select_all_button.disabled = total_count == 0

    def _on_toggle(self, path: Path, checked: bool):
        if checked:
            self._selected.add(path)
        else:
            self._selected.discard(path)
        self._update_totals()
        self._page.update()

    def _on_row_click(self, path: Path):
        if path in self._selected:
            self._selected.discard(path)
        else:
            self._selected.add(path)
        self._refresh_list()

    def _copy_path(self, path: Path):
        async def do_copy():
            clipboard = ft.Clipboard()
            await clipboard.set(str(path))
            self._show_snackbar("Path copied to clipboard")

        self._page.run_task(do_copy)

    def _open_in_explorer(self, path: Path):
        import subprocess

        if sys.platform == "win32":
            if path.is_file():
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                subprocess.Popen(["explorer", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            parent = path.parent if path.is_file() else path
            subprocess.Popen(["xdg-open", str(parent)])

    def _on_select_all(self, _event):
        visible_paths = {entry.path for entry in self._visible_entries}
        if visible_paths.issubset(self._selected):
            self._selected -= visible_paths
            self._select_all_button.text = "Select All"
        else:
            self._selected |= visible_paths
            self._select_all_button.text = "Deselect All"
        self._refresh_list()

    def _on_sort_changed(self, event):
        self._sort_key = event.control.value
        self._refresh_list()

    def _on_filter_changed(self, event):
        value = event.control.value
        self._category_filter = None if value == "all" else value
        self._refresh_list()

    def _on_search_changed(self, event):
        self._search_query = event.control.value or ""
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
        self._sort_dropdown.disabled = locked
        self._filter_dropdown.disabled = locked
        self._search_field.disabled = locked
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
        self._empty_state.visible = False
        self._set_controls_locked(locked=True)
        self._page.update()
        self._page.run_task(self._scan_task)

    async def _scan_task(self):
        assert self._cancel_event is not None
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
        self._rebuild_filter_options()
        self._refresh_list()

    def _drain_found_queue(self, found_queue: queue.Queue[JunkEntry]):
        added = False
        while not found_queue.empty():
            entry = found_queue.get_nowait()
            self._result.entries.append(entry)
            added = True
        if added:
            self._rebuild_filter_options()
            self._apply_sort_filter()
            self._results_list.controls.clear()
            for visible_entry in self._visible_entries:
                self._results_list.controls.append(self._make_row(visible_entry))
            self._total_label.value = f"{len(self._result.entries)} items, {format_size(self._result.total_bytes)}"

    def _on_clean(self, _event):
        if not self._selected:
            return

        entries = [entry for entry in self._result.entries if entry.path in self._selected]
        selected_bytes = sum(entry.size_bytes for entry in entries)

        use_trash = get_value("clean", "use_trash", "true") == "true"
        item_summary = f"{len(entries)} items ({format_size(selected_bytes)})"

        if use_trash:
            content = ft.Text(f"Move {item_summary} to trash?")
        else:
            content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.RED_700, size=24),
                            ft.Text("Permanent deletion", weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                        ],
                        spacing=8,
                    ),
                    ft.Text(f"{item_summary} will be deleted permanently. This cannot be undone."),
                ],
                tight=True,
                spacing=12,
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Confirm deletion"),
            content=content,
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._close_dialog(dialog)),
                ft.Button(
                    "Delete permanently" if not use_trash else "Delete",
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
        self._page.run_task(self._clean_task, entries)

    async def _clean_task(self, entries: list[JunkEntry]):
        deleted_set = set(id(entry) for entry in entries)
        clean_done = threading.Event()
        stats_holder: list[CleanStats] = []
        total = len(entries)
        progress_state: list[str | int] = [0, ""]

        def on_entry_cleaned(entry: JunkEntry, success: bool):
            progress_state[0] = int(progress_state[0]) + 1
            name = entry.path.name
            status = "Deleted" if success else "Failed"
            progress_state[1] = f"{status}: {name} ({progress_state[0]}/{total})"

        def run_clean():
            selected_result = ScanResult(entries=entries)
            use_trash = get_value("clean", "use_trash", "true") == "true"
            cleaner = CleanEngine(use_trash=use_trash, dry_run=False)
            stats_holder.append(cleaner.clean(selected_result, callback=on_entry_cleaned))
            clean_done.set()

        threading.Thread(target=run_clean, daemon=True).start()

        self._progress.value = 0

        while not clean_done.is_set():
            processed = int(progress_state[0])
            self._progress.value = processed / total if total else 0
            self._status.value = str(progress_state[1]) or f"Cleaning 0/{total}..."
            self._page.update()
            await asyncio.sleep(0.1)

        stats = stats_holder[0]

        deleted_paths = {entry.path for entry in entries}
        self._result.entries = [entry for entry in self._result.entries if id(entry) not in deleted_set]
        self._selected -= deleted_paths
        self._scan_button.disabled = False
        self._progress.visible = False
        self._progress.value = None

        entry_count = len(self._result.entries)
        if stats.errors:
            self._status.value = f"{entry_count} items remaining, {stats.skipped} failed"
            self._show_error_dialog(stats)
        else:
            self._status.value = f"{entry_count} items remaining"
            self._show_snackbar(f"Deleted {stats.deleted} items ({format_size(stats.bytes_freed)})")

        self._set_controls_locked(locked=False)
        self._rebuild_filter_options()
        self._refresh_list()

    def _show_error_dialog(self, stats: CleanStats):
        error_lines: list[ft.Control] = [ft.Text(error, size=12) for error in stats.errors]
        dialog = ft.AlertDialog(
            title=ft.Text(f"Deleted {stats.deleted}, failed {stats.skipped}"),
            content=ft.Column(error_lines, tight=True, scroll=ft.ScrollMode.AUTO, height=200),
            actions=[ft.TextButton("OK", on_click=lambda _: self._page.pop_dialog())],
        )
        self._page.show_dialog(dialog)

    def _on_settings_click(self, _event):
        use_trash = get_value("clean", "use_trash", "true") == "true"
        trash_switch = ft.Switch(label="Move to trash instead of permanent delete", value=use_trash)

        def save_settings(_event):
            save_value("clean", "use_trash", "true" if trash_switch.value else "false")
            self._page.pop_dialog()
            self._show_snackbar("Settings saved")

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Settings"),
            content=ft.Column([trash_switch], tight=True, width=400),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: self._page.pop_dialog()),
                ft.Button("Save", on_click=save_settings),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._page.show_dialog(dialog)

    def _on_about_click(self, _event):
        dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=32, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=20, weight=ft.FontWeight.BOLD),
                ],
                spacing=12,
            ),
            content=ft.Column(
                [
                    ft.Text(f"Version {_VERSION}", size=14),
                    ft.Text(
                        "Reclaim disk space from game clients",
                        size=13,
                        color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE),
                    ),
                    ft.Divider(height=16),
                    ft.Text("Keyboard shortcuts", weight=ft.FontWeight.BOLD, size=13),
                    ft.Text("Ctrl+A — select / deselect all", size=12),
                    ft.Text("Delete — clean selected items", size=12),
                    ft.Text("Escape — cancel scan / deselect / clear search", size=12),
                    ft.Divider(height=16),
                    ft.Row(
                        [
                            ft.TextButton("GitHub", icon=ft.Icons.CODE, url=_GITHUB_URL),
                            ft.TextButton("Boosty", icon=ft.Icons.FAVORITE, url=_BOOSTY_URL),
                        ],
                        spacing=8,
                    ),
                ],
                tight=True,
                width=360,
                spacing=8,
            ),
            actions=[ft.TextButton("Close", on_click=lambda _: self._page.pop_dialog())],
        )
        self._page.show_dialog(dialog)

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
