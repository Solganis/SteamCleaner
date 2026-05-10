import asyncio
import contextlib
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
from steamcleaner.ui.gui.i18n import LANGUAGES, get_lang, init_lang, set_lang, t, t_category
from steamcleaner.utils.config import get_value, save_many, save_value
from steamcleaner.utils.fs import format_size
from steamcleaner.utils.logging import is_logging_enabled, log_file_path, set_logging_enabled

_VERSION = "0.9.0"
_GITHUB_URL = "https://github.com/Solganis/SteamCleaner"
_BOOSTY_URL = "https://boosty.to/solganis"
_DONATE_URL = "https://www.donationalerts.com/r/Solganis"
_TON_ADDRESS = "UQAZDskr7UZE9Hn8Q8asCfmYIsicgL0KS9YNvRJ5NF53OPPo"
_USDT_TRC20_ADDRESS = "TG32fyLCxPcTCmtFXayDkvAvAF9goci9st"

_PADDING_H = 16
_CATEGORY_COLORS = {
    "redistributable": ft.Colors.ORANGE_700,
    "shader_cache": ft.Colors.PURPLE_700,
    "crash_dump": ft.Colors.RED_700,
    "old_log": ft.Colors.BLUE_GREY_700,
    "installer": ft.Colors.AMBER_700,
    "cross_platform": ft.Colors.TEAL_700,
}


class WindowHider:
    """Finds the Flutter window handle so Python can show it when ready."""

    def __init__(self):
        self._hwnd: int | None = None
        self._stop = threading.Event()

    @classmethod
    def from_hwnd(cls, hwnd: int | None) -> "WindowHider":
        instance = cls()
        instance._stop.set()
        instance._hwnd = hwnd
        return instance

    def start(self):
        if sys.platform != "win32":
            return
        threading.Thread(target=self._find_window, daemon=True).start()

    def stop(self):
        self._stop.set()

    # noinspection PyUnresolvedReferences
    def show(self):
        if self._hwnd is None or sys.platform != "win32":
            return
        import ctypes

        user32 = ctypes.windll.user32  # noqa: E1101
        user32.ShowWindow(self._hwnd, 5)

    # noinspection PyUnresolvedReferences
    def _find_window(self):
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32  # noqa: E1101
        enum_cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        swp_nosize = 0x0001
        swp_nozorder = 0x0004
        swp_noactivate = 0x0010

        # noinspection PyUnresolvedReferences
        def find_flutter() -> int | None:
            found: list[int | None] = [None]

            # noinspection PyUnresolvedReferences
            def callback(window_handle, _):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(window_handle, buf, 256)
                if "FLUTTER" in buf.value.upper():
                    found[0] = window_handle
                    return False
                return True

            user32.EnumWindows(enum_cb(callback), 0)
            return found[0]

        while not self._stop.is_set():
            hwnd = find_flutter()
            if hwnd:
                self._hwnd = hwnd
                break
            time.sleep(0.001)

        if self._hwnd is None:
            return

        while not self._stop.is_set():
            user32.SetWindowPos(hwnd, 0, -32000, -32000, 0, 0, swp_nosize | swp_nozorder | swp_noactivate)
            time.sleep(0.005)


class SteamCleanerGUI:
    def __init__(self, page: ft.Page, window_hider: WindowHider | None = None):
        init_lang()
        self._page = page
        self._result = ScanResult()
        self._selected: set[Path] = set()
        self._visible_entries: list[JunkEntry] = []
        self._sort_key = "size_desc"
        self._category_filter: str | None = None
        self._search_query = ""
        self._cancel_event: threading.Event | None = None
        self._geometry_save_timer: threading.Timer | None = None
        self._text_input_focused = False
        self._dialog_open = False
        self._initialized = False
        self._window_hider = window_hider or WindowHider()
        self._status = ft.Text(t("ready"), size=12)
        self._total_label = ft.Text("", size=12)
        self._theme_button = ft.IconButton()
        self._scan_button = ft.Button(t("scan"))
        self._clean_button = ft.Button(t("clean_selected"), disabled=True)
        self._select_all_button = ft.TextButton(t("select_all"), disabled=True)
        self._sort_dropdown = ft.Dropdown(width=160)
        self._filter_dropdown = ft.Dropdown(width=160)
        self._search_field = ft.TextField()
        self._progress = ft.ProgressBar(opacity=0)
        self._results_list = ft.ListView()
        self._empty_state = ft.Column()
        self._setup_page()

    async def initialize(self):
        self._window_hider.stop()
        self._page.update()
        await asyncio.sleep(0.15)
        self._build_ui()
        self._page.window.visible = True
        self._page.update()
        await asyncio.sleep(0.05)
        self._window_hider.show()
        self._initialized = True

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
        self._page.window.visible = False
        self._page.window.width = int(get_value("window", "width") or "960")
        self._page.window.height = int(get_value("window", "height") or "640")
        saved_left = get_value("window", "left")
        saved_top = get_value("window", "top")
        if saved_left is not None and saved_top is not None:
            left_val = int(saved_left)
            top_val = int(saved_top)
            if left_val > -30000 and top_val > -30000:
                self._page.window.left = left_val
                self._page.window.top = top_val
        self._page.window.min_width = 720
        self._page.window.min_height = 480
        self._page.window.on_event = self.on_window_event
        self._page.on_keyboard_event = self._on_keyboard
        self._page.padding = 0
        self._page.spacing = 0

    def _save_window_geometry(self):
        window = self._page.window
        if window.width is None or window.height is None or window.left is None or window.top is None:
            return
        if int(window.left) <= -30000 or int(window.top) <= -30000:
            return
        save_many(
            "window",
            {
                "width": str(int(window.width)),
                "height": str(int(window.height)),
                "left": str(int(window.left)),
                "top": str(int(window.top)),
            },
        )

    def on_window_event(self, event: ft.WindowEvent):
        if not self._initialized:
            return
        match event.type:
            case ft.WindowEventType.RESIZED | ft.WindowEventType.MOVED:
                if self._geometry_save_timer is not None:
                    self._geometry_save_timer.cancel()
                timer = threading.Timer(0.3, self._save_window_geometry)
                self._geometry_save_timer = timer
                timer.start()

    def _set_text_input_focus(self, focused: bool):
        self._text_input_focused = focused

    def _on_keyboard(self, event: ft.KeyboardEvent):
        if event.key == "Escape":
            if self._dialog_open:
                return
            if self._cancel_event is not None:
                self._cancel_event.set()
            elif self._selected:
                self._selected.clear()
                self._select_all_button.text = t("select_all")
                self._refresh_list()
            elif self._text_input_focused:
                self._search_field.value = ""
                self._search_query = ""
                # noinspection PyUnresolvedReferences
                self._page.focus()
                self._refresh_list()
            return

        if self._text_input_focused:
            return

        if event.key == "F5":
            self.on_scan(None)
        elif event.key == "Q" and event.ctrl:
            self._page.run_task(self._page.window.close)
        elif event.key == "A" and event.ctrl:
            self._on_select_all(None)
        elif event.key == "Delete" and self._selected and self._cancel_event is None:
            self._on_clean(None)

    def _build_ui(self):
        is_dark = self._page.theme_mode == ft.ThemeMode.DARK

        self._status = ft.Text(t("ready"), size=12, color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE))
        self._total_label = ft.Text("", size=12, weight=ft.FontWeight.W_500)

        self._theme_button = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE,
            tooltip=t("theme_to_light") if is_dark else t("theme_to_dark"),
            on_click=self.on_toggle_theme,
            icon_size=20,
        )

        self._scan_button = ft.Button(
            t("scan"),
            icon=ft.Icons.SEARCH,
            on_click=self.on_scan,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )
        self._clean_button = ft.Button(
            t("clean_selected"),
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
            t("select_all"),
            on_click=self._on_select_all,
            disabled=True,
        )

        self._sort_dropdown = ft.Dropdown(
            width=180,
            value="size_desc",
            label=t("sort_by"),
            options=[
                ft.dropdown.Option("size_desc", t("size_largest")),
                ft.dropdown.Option("size_asc", t("size_smallest")),
                ft.dropdown.Option("category", t("category")),
                ft.dropdown.Option("path", t("path")),
            ],
            on_select=self._on_sort_changed,
            dense=True,
            text_size=13,
        )

        self._filter_dropdown = ft.Dropdown(
            width=180,
            value="all",
            label=t("filter"),
            options=[ft.dropdown.Option("all", t("all_categories"))],
            on_select=self._on_filter_changed,
            dense=True,
            text_size=13,
        )

        self._search_field = ft.TextField(
            hint_text=t("search"),
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            dense=True,
            text_size=13,
            on_change=self._on_search_changed,
            on_focus=lambda _: self._set_text_input_focus(True),
            on_blur=lambda _: self._set_text_input_focus(False),
        )

        self._progress = ft.ProgressBar(opacity=0)
        self._results_list = ft.ListView(expand=True, spacing=1, padding=ft.Padding.symmetric(horizontal=_PADDING_H))

        settings_button = ft.IconButton(
            icon=ft.Icons.SETTINGS,
            tooltip=t("settings"),
            on_click=self._on_settings_click,
            icon_size=20,
        )
        about_button = ft.IconButton(
            icon=ft.Icons.INFO_OUTLINE,
            tooltip=t("about"),
            on_click=self._on_about_click,
            icon_size=20,
        )

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=24, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=18, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    settings_button,
                    about_button,
                    self._theme_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=4,
            ),
            padding=ft.Padding.symmetric(horizontal=_PADDING_H, vertical=10),
        )

        toolbar = ft.Container(
            content=ft.Row(
                [
                    self._scan_button,
                    self._select_all_button,
                    ft.VerticalDivider(width=1),
                    self._sort_dropdown,
                    self._filter_dropdown,
                    self._search_field,
                    ft.VerticalDivider(width=1),
                    self._clean_button,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=_PADDING_H, vertical=6),
        )

        self._empty_state = ft.Column(
            [
                ft.Container(expand=True),
                ft.Icon(ft.Icons.SEARCH_OFF, size=48, color=ft.Colors.with_opacity(0.3, ft.Colors.ON_SURFACE)),
                ft.Text(
                    t("empty_scan"),
                    size=15,
                    color=ft.Colors.with_opacity(0.4, ft.Colors.ON_SURFACE),
                ),
                ft.Container(expand=True),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            expand=True,
        )

        status_bar = ft.Container(
            content=ft.Row(
                [
                    self._status,
                    ft.Container(expand=True),
                    self._total_label,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.symmetric(horizontal=_PADDING_H, vertical=6),
            bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
        )

        self._page.add(
            header,
            ft.Divider(height=1),
            toolbar,
            ft.Divider(height=1),
            ft.Stack([self._results_list, self._empty_state], expand=True),
            self._progress,
            status_bar,
        )
        self._page.update()

    def _make_row(self, entry: JunkEntry, index: int) -> ft.Container:
        entry_path = entry.path
        is_selected = entry_path in self._selected

        checkbox = ft.Checkbox(
            value=is_selected,
            on_change=lambda event, path=entry_path: self._on_toggle(path, event.control.value),
        )

        badge_color = _CATEGORY_COLORS.get(entry.category.value, ft.Colors.GREY_700)
        badge = ft.Container(
            content=ft.Text(t_category(entry.category.value), size=11, color=ft.Colors.WHITE),
            bgcolor=badge_color,
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
        )

        actions_menu = ft.PopupMenuButton(
            icon=ft.Icons.MORE_VERT,
            icon_size=16,
            padding=0,
            items=[
                ft.PopupMenuItem(
                    t("open_in_explorer"),
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda _, path=entry_path: self._open_in_explorer(path),
                ),
                ft.PopupMenuItem(
                    t("copy_path"),
                    icon=ft.Icons.CONTENT_COPY,
                    on_click=lambda _, path=entry_path: self._copy_path(path),
                ),
            ],
        )

        row_bg = ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE) if index % 2 == 0 else None
        if is_selected:
            row_bg = ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY)

        return ft.Container(
            content=ft.Row(
                [
                    checkbox,
                    ft.Text(
                        format_size(entry.size_bytes),
                        width=80,
                        text_align=ft.TextAlign.RIGHT,
                        weight=ft.FontWeight.W_500,
                        size=13,
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
            border_radius=4,
            bgcolor=row_bg,
            ink=True,
            on_click=lambda event, path=entry_path: self._on_row_click(path),
        )

    def _apply_sort_filter(self):
        entries = self._result.entries
        if self._category_filter and self._category_filter != "all":
            entries = [entry for entry in entries if entry.category.value == self._category_filter]
        if self._search_query:
            query_lower = self._search_query.lower()
            entries = [entry for entry in entries if query_lower in str(entry.path).lower()]
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
        for index, entry in enumerate(self._visible_entries):
            self._results_list.controls.append(self._make_row(entry, index))
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
            text_control.value = t("empty_filter")
            self._empty_state.visible = True
        else:
            icon_control.name = ft.Icons.SEARCH_OFF
            text_control.value = t("empty_scan")
            self._empty_state.visible = True

    def _rebuild_filter_options(self):
        categories = sorted({entry.category.value for entry in self._result.entries})
        options: list[ft.dropdown.Option] = [ft.dropdown.Option("all", t("all_categories"))]
        for category in categories:
            options.append(ft.dropdown.Option(category, t_category(category)))
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
        filter_note = t("total_shown", shown=visible_count) if visible_count != total_count else ""
        self._total_label.value = (
            t(
                "total_selected",
                selected=selected_formatted,
                total=total_formatted,
                sel_count=len(self._selected),
                total_count=total_count,
            )
            + filter_note
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
            self._show_snackbar(t("path_copied"))

        self._page.run_task(do_copy)

    @staticmethod
    def _open_in_explorer(path: Path):
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
            self._select_all_button.text = t("select_all")
        else:
            self._selected |= visible_paths
            self._select_all_button.text = t("deselect_all")
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

    def on_toggle_theme(self, _event):
        if self._page.theme_mode == ft.ThemeMode.DARK:
            self._page.theme_mode = ft.ThemeMode.LIGHT
            self._theme_button.icon = ft.Icons.DARK_MODE
            self._theme_button.tooltip = t("theme_to_dark")
            save_value("ui", "theme", "light")
        else:
            self._page.theme_mode = ft.ThemeMode.DARK
            self._theme_button.icon = ft.Icons.LIGHT_MODE
            self._theme_button.tooltip = t("theme_to_light")
            save_value("ui", "theme", "dark")
        self._page.update()

    def _reset_scan_ui(self):
        self._scan_button.text = t("scan")
        self._scan_button.icon = ft.Icons.SEARCH
        self._progress.opacity = 0
        self._cancel_event = None

    def _set_controls_locked(self, locked: bool):
        self._clean_button.disabled = locked or not self._selected
        self._select_all_button.disabled = locked or len(self._result.entries) == 0
        self._sort_dropdown.disabled = locked
        self._filter_dropdown.disabled = locked
        self._search_field.disabled = locked
        self._results_list.disabled = locked
        self._results_list.opacity = 0.4 if locked else 1.0

    def on_scan(self, _event):
        if self._cancel_event is not None:
            self._cancel_event.set()
            return

        self._cancel_event = threading.Event()
        self._scan_button.text = t("stop")
        self._scan_button.icon = ft.Icons.STOP
        self._progress.opacity = 1
        self._status.value = t("scanning")
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
        status_text = [t("scanning")]
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
            except (OSError, ValueError, KeyError):  # fmt: skip  # parens required: flet build bundles Python 3.12
                status_text[0] = t("scan_failed")
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
            self._status.value = t("stopped", count=entry_count)
        elif status_text[0] == t("scan_failed"):
            self._status.value = t("scan_failed")
        else:
            self._status.value = t("found_items", count=entry_count, size=format_size(self._result.total_bytes))

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
            for index, visible_entry in enumerate(self._visible_entries):
                self._results_list.controls.append(self._make_row(visible_entry, index))
            self._total_label.value = t(
                "scan_progress", items=len(self._result.entries), size=format_size(self._result.total_bytes)
            )

    def _on_clean(self, _event):
        if not self._selected:
            return

        entries = [entry for entry in self._result.entries if entry.path in self._selected]
        selected_bytes = sum(entry.size_bytes for entry in entries)

        use_trash = get_value("clean", "use_trash", "true") == "true"
        item_summary = f"{len(entries)} items ({format_size(selected_bytes)})"

        if use_trash:
            content = ft.Text(t("move_to_trash", summary=item_summary))
        else:
            content = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.RED_700, size=24),
                            ft.Text(t("permanent_deletion"), weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                        ],
                        spacing=8,
                    ),
                    ft.Text(t("permanent_warning", summary=item_summary)),
                ],
                tight=True,
                spacing=12,
            )

        dialog = ft.AlertDialog(
            title=ft.Text(t("confirm_deletion")),
            content=content,
            actions=[
                ft.TextButton(t("cancel"), on_click=lambda _: self._close_dialog()),
                ft.Button(
                    t("delete_permanently") if not use_trash else t("delete"),
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.RED_700,
                    on_click=lambda _: self._confirm_clean(entries),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dialog)

    def _confirm_clean(self, entries: list[JunkEntry]):
        self._close_dialog()
        self._status.value = t("cleaning")
        self._progress.opacity = 1
        self._set_controls_locked(locked=True)
        self._scan_button.disabled = True
        self._page.update()
        self._page.run_task(self._clean_task, entries)

    async def _clean_task(self, entries: list[JunkEntry]):
        deleted_set = {id(entry) for entry in entries}
        clean_done = threading.Event()
        stats_holder: list[CleanStats] = []
        total = len(entries)
        progress_state: list[str | int] = [0, ""]

        def on_entry_cleaned(entry: JunkEntry, success: bool):
            progress_state[0] = int(progress_state[0]) + 1
            name = entry.path.name
            status = t("deleted") if success else t("failed")
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
            self._status.value = str(progress_state[1]) or t("cleaning_progress", total=total)
            self._page.update()
            await asyncio.sleep(0.1)

        stats = stats_holder[0]

        deleted_paths = {entry.path for entry in entries}
        self._result.entries = [entry for entry in self._result.entries if id(entry) not in deleted_set]
        self._selected -= deleted_paths
        self._scan_button.disabled = False
        self._progress.opacity = 0
        self._progress.value = None

        entry_count = len(self._result.entries)
        if stats.errors:
            self._status.value = t("items_remaining_errors", count=entry_count, errors=stats.skipped)
            self._show_error_dialog(stats)
        else:
            self._status.value = t("items_remaining", count=entry_count)
            self._show_snackbar(t("deleted_summary", count=stats.deleted, size=format_size(stats.bytes_freed)))

        self._set_controls_locked(locked=False)
        self._rebuild_filter_options()
        self._refresh_list()

    def _show_error_dialog(self, stats: CleanStats):
        error_lines: list[ft.Control] = [ft.Text(error, size=12) for error in stats.errors]
        dialog = ft.AlertDialog(
            title=ft.Text(t("deleted_failed_title", deleted=stats.deleted, failed=stats.skipped)),
            content=ft.Column(error_lines, tight=True, scroll=ft.ScrollMode.AUTO, height=200),
            actions=[ft.TextButton(t("close"), on_click=lambda _: self._close_dialog())],
        )
        self._open_dialog(dialog)

    def _on_settings_click(self, _event):
        use_trash = get_value("clean", "use_trash", "true") == "true"
        delete_hint = ft.Text(
            t("delete_mode_hint_trash") if use_trash else t("delete_mode_hint_permanent"),
            size=13,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE) if use_trash else ft.Colors.RED_700,
        )

        def on_delete_mode_changed(event: ft.Event[ft.SegmentedButton]):
            selected_mode = event.control.selected[0] if event.control.selected else "trash"
            save_value("clean", "use_trash", "true" if selected_mode == "trash" else "false")
            if selected_mode == "permanent":
                delete_hint.value = t("delete_mode_hint_permanent")
                delete_hint.color = ft.Colors.RED_700
            else:
                delete_hint.value = t("delete_mode_hint_trash")
                delete_hint.color = ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE)
            self._page.update()

        delete_mode = ft.SegmentedButton(
            selected=["trash" if use_trash else "permanent"],
            segments=[
                ft.Segment(
                    value="trash",
                    label=ft.Text(t("delete_mode_trash")),
                    icon=ft.Icon(ft.Icons.DELETE_OUTLINE),
                ),
                ft.Segment(
                    value="permanent",
                    label=ft.Text(t("delete_mode_permanent")),
                    icon=ft.Icon(ft.Icons.DELETE_FOREVER),
                ),
            ],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            on_change=on_delete_mode_changed,
        )

        def on_lang_changed(event: ft.Event[ft.Dropdown]):
            new_lang = event.control.value
            if new_lang and new_lang != get_lang():
                set_lang(new_lang)
                self._close_dialog()
                self._page.controls.clear()
                self._page.update()
                self._build_ui()
                self._rebuild_filter_options()
                self._refresh_list()

        lang_dropdown = ft.Dropdown(
            width=200,
            label=t("language"),
            value=get_lang(),
            options=[ft.dropdown.Option(code, label) for code, label in LANGUAGES.items()],
            dense=True,
            on_select=on_lang_changed,
        )

        log_button_active = is_logging_enabled() and log_file_path().exists()
        open_log_button = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            tooltip=t("open_log_file") if log_button_active else None,
            icon_size=18,
            on_click=lambda _: self._open_in_explorer(log_file_path()),
            opacity=1.0 if log_button_active else 0.0,
            disabled=not log_button_active,
        )

        def on_logging_toggled(event: ft.Event[ft.Switch]):
            set_logging_enabled(event.control.value)
            active = event.control.value and log_file_path().exists()
            open_log_button.opacity = 1.0 if active else 0.0
            open_log_button.disabled = not active
            open_log_button.tooltip = t("open_log_file") if active else None
            self._page.update()

        logging_switch = ft.Switch(
            label=t("logging"),
            value=is_logging_enabled(),
            tooltip=t("logging_hint"),
            on_change=on_logging_toggled,
        )

        dialog = ft.AlertDialog(
            title=ft.Text(t("settings")),
            content=ft.Column(
                [
                    ft.Text(t("delete_mode"), size=13, weight=ft.FontWeight.W_500),
                    delete_mode,
                    delete_hint,
                    ft.Divider(height=24),
                    ft.Row(
                        [lang_dropdown, logging_switch, open_log_button],
                        spacing=8,
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                ],
                tight=True,
                width=400,
                spacing=8,
            ),
            actions=[
                ft.TextButton(t("close"), on_click=lambda _: self._close_dialog()),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._open_dialog(dialog)

    def _on_about_click(self, _event):
        dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=28, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=18, weight=ft.FontWeight.BOLD),
                ],
                spacing=12,
            ),
            content=ft.Column(
                [
                    ft.Text(t("version", version=_VERSION), size=13),
                    ft.Text(
                        t("description"),
                        size=12,
                        color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE),
                    ),
                    ft.Divider(height=16),
                    ft.Text(t("keyboard_shortcuts"), weight=ft.FontWeight.BOLD, size=13),
                    ft.Text(t("shortcut_scan"), size=12),
                    ft.Text(t("shortcut_select_all"), size=12),
                    ft.Text(t("shortcut_delete"), size=12),
                    ft.Text(t("shortcut_escape"), size=12),
                    ft.Text(t("shortcut_quit"), size=12),
                    ft.Divider(height=16),
                    ft.Row(
                        [
                            ft.TextButton("GitHub", icon=ft.Icons.CODE, url=_GITHUB_URL),
                            ft.TextButton("Donate", icon=ft.Icons.VOLUNTEER_ACTIVISM, url=_DONATE_URL),
                            ft.TextButton("Boosty", icon=ft.Icons.FAVORITE, url=_BOOSTY_URL),
                        ],
                        spacing=8,
                    ),
                    ft.Row(
                        [
                            ft.TextButton(
                                "TON",
                                icon=ft.Icons.CURRENCY_BITCOIN,
                                tooltip=t("click_to_copy"),
                                on_click=lambda event: self._copy_with_feedback(event, _TON_ADDRESS, "TON"),
                            ),
                            ft.TextButton(
                                "USDT (TRC-20)",
                                icon=ft.Icons.CURRENCY_BITCOIN,
                                tooltip=t("click_to_copy"),
                                on_click=lambda event: self._copy_with_feedback(
                                    event, _USDT_TRC20_ADDRESS, "USDT (TRC-20)"
                                ),
                            ),
                        ],
                        spacing=8,
                    ),
                ],
                tight=True,
                width=360,
                spacing=6,
            ),
            actions=[ft.TextButton(t("close"), on_click=lambda _: self._close_dialog())],
        )
        self._open_dialog(dialog)

    def _open_dialog(self, dialog: ft.AlertDialog):
        self._dialog_open = True
        dialog.on_dismiss = lambda _: setattr(self, "_dialog_open", False)
        self._page.show_dialog(dialog)

    def _close_dialog(self):
        self._dialog_open = False
        self._page.pop_dialog()

    def _copy_with_feedback(self, event, address: str, label: str):
        button = event.control

        async def do_copy():
            clipboard = ft.Clipboard()
            await clipboard.set(address)
            button.text = t("copied")
            button.icon = ft.Icons.CHECK
            try:
                button.update()
            except RuntimeError:
                return
            await asyncio.sleep(1.5)
            button.text = label
            button.icon = ft.Icons.CURRENCY_BITCOIN
            with contextlib.suppress(RuntimeError):
                button.update()

        self._page.run_task(do_copy)

    def _show_snackbar(self, message: str):
        snackbar = ft.SnackBar(content=ft.Text(message), duration=4000, open=True)
        self._page.overlay.append(snackbar)
        self._page.update()


def run_gui():
    hider = WindowHider()
    hider.start()

    async def main(page: ft.Page):
        gui = SteamCleanerGUI(page, hider)
        await gui.initialize()

    ft.run(main)
