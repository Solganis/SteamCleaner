from __future__ import annotations

import threading

import darkdetect
import flet as ft

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.junk import JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.config import get_value, save_value
from steamcleaner.utils.fs import format_size


class SteamCleanerGUI:
    def __init__(self, page: ft.Page):
        self._page = page
        self._result = ScanResult()
        self._selected: set[int] = set()
        self._cancel_event: threading.Event | None = None
        self._setup_page()
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
        self._page.window.width = int(get_value("window", "width", "960"))
        self._page.window.height = int(get_value("window", "height", "640"))
        self._page.window.min_width = 720
        self._page.window.min_height = 480
        saved_left = get_value("window", "left")
        saved_top = get_value("window", "top")
        if saved_left is not None and saved_top is not None:
            self._page.window.left = int(saved_left)
            self._page.window.top = int(saved_top)
        self._page.window.on_event = self._on_window_event
        self._page.padding = 0

    def _on_window_event(self, e: ft.WindowEvent):
        if e.data == "close":
            save_value("window", "width", str(int(self._page.window.width)))
            save_value("window", "height", str(int(self._page.window.height)))
            save_value("window", "left", str(int(self._page.window.left)))
            save_value("window", "top", str(int(self._page.window.top)))

    def _build_ui(self):
        self._status = ft.Text("Ready", size=14)
        self._total_label = ft.Text("", size=14, weight=ft.FontWeight.BOLD)

        is_dark = self._page.theme_mode == ft.ThemeMode.DARK
        self._theme_btn = ft.IconButton(
            icon=ft.Icons.LIGHT_MODE if is_dark else ft.Icons.DARK_MODE,
            tooltip="Switch to light theme" if is_dark else "Switch to dark theme",
            on_click=self._on_toggle_theme,
        )

        self._scan_btn = ft.ElevatedButton(
            "Scan",
            icon=ft.Icons.SEARCH,
            on_click=self._on_scan,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )
        self._clean_btn = ft.ElevatedButton(
            "Clean Selected",
            icon=ft.Icons.DELETE_SWEEP,
            on_click=self._on_clean,
            disabled=True,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.RED_700,
        )
        self._select_all_btn = ft.TextButton(
            "Select All",
            on_click=self._on_select_all,
            disabled=True,
        )

        self._progress = ft.ProgressBar(visible=False)

        self._results_list = ft.ListView(expand=True, spacing=2, padding=ft.padding.symmetric(horizontal=16))

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CLEANING_SERVICES, size=28, color=ft.Colors.BLUE_400),
                    ft.Text("SteamCleaner", size=22, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True),
                    self._status,
                    self._theme_btn,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
        )

        toolbar = ft.Container(
            content=ft.Row(
                [
                    self._scan_btn,
                    self._select_all_btn,
                    ft.Container(expand=True),
                    self._total_label,
                    self._clean_btn,
                ],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=20, vertical=8),
        )

        self._page.add(
            header,
            self._progress,
            toolbar,
            ft.Divider(height=1),
            ft.Container(content=self._results_list, expand=True),
        )

    def _make_row(self, index: int, entry: JunkEntry) -> ft.Container:
        cb = ft.Checkbox(
            value=index in self._selected,
            on_change=lambda e, i=index: self._on_toggle(i, e.control.value),
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
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
        )

        return ft.Container(
            content=ft.Row(
                [
                    cb,
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
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            border_radius=6,
            ink=True,
            on_click=lambda e, i=index: self._on_row_click(i),
        )

    def _refresh_list(self):
        self._results_list.controls.clear()
        for i, entry in enumerate(self._result.entries):
            self._results_list.controls.append(self._make_row(i, entry))
        self._update_totals()
        self._page.update()

    def _update_totals(self):
        selected_bytes = sum(self._result.entries[i].size_bytes for i in self._selected)
        total = format_size(self._result.total_bytes)
        sel = format_size(selected_bytes)
        self._total_label.value = f"{sel} / {total} selected ({len(self._selected)}/{len(self._result.entries)})"
        has_selection = len(self._selected) > 0
        self._clean_btn.disabled = not has_selection
        self._select_all_btn.disabled = len(self._result.entries) == 0

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

    def _on_select_all(self, _e):
        if len(self._selected) == len(self._result.entries):
            self._selected.clear()
            self._select_all_btn.text = "Select All"
        else:
            self._selected = set(range(len(self._result.entries)))
            self._select_all_btn.text = "Deselect All"
        self._refresh_list()

    def _on_toggle_theme(self, _e):
        if self._page.theme_mode == ft.ThemeMode.DARK:
            self._page.theme_mode = ft.ThemeMode.LIGHT
            self._theme_btn.icon = ft.Icons.DARK_MODE
            self._theme_btn.tooltip = "Switch to dark theme"
            save_value("ui", "theme", "light")
        else:
            self._page.theme_mode = ft.ThemeMode.DARK
            self._theme_btn.icon = ft.Icons.LIGHT_MODE
            self._theme_btn.tooltip = "Switch to light theme"
            save_value("ui", "theme", "dark")
        self._page.update()

    def _on_scan(self, _e):
        if self._cancel_event is not None:
            self._cancel_event.set()
            return

        self._cancel_event = threading.Event()
        self._scan_btn.text = "Stop"
        self._scan_btn.icon = ft.Icons.STOP
        self._progress.visible = True
        self._status.value = "Scanning..."
        self._page.update()

        cancel = self._cancel_event

        def do_scan():
            from steamcleaner.platform import create_adapter

            platform = create_adapter()
            exclusions = ExclusionRegistry()
            engine = ScanEngine(platform, exclusions)
            self._result = engine.scan(cancel=cancel)
            self._selected.clear()
            self._scan_btn.text = "Scan"
            self._scan_btn.icon = ft.Icons.SEARCH
            self._progress.visible = False
            self._cancel_event = None
            count = len(self._result.entries)
            if cancel.is_set():
                self._status.value = f"Stopped — {count} items found so far"
            else:
                self._status.value = f"Found {count} items — {format_size(self._result.total_bytes)}"
            self._refresh_list()

        threading.Thread(target=do_scan, daemon=True).start()

    def _on_clean(self, _e):
        if not self._selected:
            return

        entries = [self._result.entries[i] for i in sorted(self._selected)]
        selected_result = ScanResult(entries=entries)
        cleaner = CleanEngine(use_trash=True, dry_run=False)
        stats = cleaner.clean(selected_result)

        self._show_snackbar(f"Deleted {stats.deleted} items ({format_size(stats.bytes_freed)})")
        self._on_scan(None)

    def _show_snackbar(self, message: str):
        self._page.open(ft.SnackBar(content=ft.Text(message), duration=4000))


def run_gui():
    ft.app(target=lambda page: SteamCleanerGUI(page))
