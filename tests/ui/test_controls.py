from pathlib import Path

import flet as ft

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.ui.gui.app import SteamCleanerGUI
from steamcleaner.ui.gui.i18n import t


def _make_entry(
    name: str,
    category: JunkCategory = JunkCategory.REDISTRIBUTABLE,
    size: int = 1024,
) -> JunkEntry:
    return JunkEntry(
        path=Path(f"C:/Games/{name}"),
        category=category,
        size_bytes=size,
        client_name="Steam",
    )


ENTRY_SMALL = _make_entry("small_redist", JunkCategory.REDISTRIBUTABLE, 100)
ENTRY_MEDIUM = _make_entry("medium_shader", JunkCategory.SHADER_CACHE, 5000)
ENTRY_LARGE = _make_entry("large_dump", JunkCategory.CRASH_DUMP, 90000)


# noinspection PyProtectedMember
def _populate_list(gui: SteamCleanerGUI, entries: list[JunkEntry]):
    gui._result = ScanResult(entries=list(entries))
    gui._visible_entries = list(entries)
    gui._results_list.controls.clear()
    for index, entry in enumerate(entries):
        gui._results_list.controls.append(gui._make_row(entry, index))


# noinspection PyProtectedMember
class TestOnSelectAll:
    def test_select_all_adds_paths(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui_with_ui._on_select_all(None)
        assert ENTRY_SMALL.path in gui_with_ui._selected
        assert ENTRY_MEDIUM.path in gui_with_ui._selected
        assert ENTRY_LARGE.path in gui_with_ui._selected

    def test_deselect_all_removes_paths(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM])
        gui_with_ui._selected = {ENTRY_SMALL.path, ENTRY_MEDIUM.path}
        gui_with_ui._on_select_all(None)
        assert ENTRY_SMALL.path not in gui_with_ui._selected
        assert ENTRY_MEDIUM.path not in gui_with_ui._selected

    def test_checkboxes_toggled_on(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM])
        gui_with_ui._on_select_all(None)
        for container in gui_with_ui._results_list.controls:
            checkbox = container.content.controls[0]
            assert checkbox.value is True

    def test_checkboxes_toggled_off(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM])
        gui_with_ui._selected = {ENTRY_SMALL.path, ENTRY_MEDIUM.path}
        gui_with_ui._on_select_all(None)
        for container in gui_with_ui._results_list.controls:
            checkbox = container.content.controls[0]
            assert checkbox.value is False

    def test_button_text_toggles(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL])
        gui_with_ui._on_select_all(None)
        assert gui_with_ui._select_all_button.text == t("deselect_all")
        gui_with_ui._on_select_all(None)
        assert gui_with_ui._select_all_button.text == t("select_all")


# noinspection PyProtectedMember
class TestOnRowClick:
    def test_click_selects_row(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL])
        gui_with_ui._on_row_click(ENTRY_SMALL.path)
        assert ENTRY_SMALL.path in gui_with_ui._selected
        checkbox = gui_with_ui._results_list.controls[0].content.controls[0]
        assert checkbox.value is True

    def test_click_deselects_row(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL])
        gui_with_ui._selected.add(ENTRY_SMALL.path)
        gui_with_ui._on_row_click(ENTRY_SMALL.path)
        assert ENTRY_SMALL.path not in gui_with_ui._selected
        checkbox = gui_with_ui._results_list.controls[0].content.controls[0]
        assert checkbox.value is False

    def test_click_updates_background(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL])
        container = gui_with_ui._results_list.controls[0]
        gui_with_ui._on_row_click(ENTRY_SMALL.path)
        assert container.bgcolor == ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY)
        gui_with_ui._on_row_click(ENTRY_SMALL.path)
        assert container.bgcolor == ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE)

    def test_click_only_affects_target(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        checkbox_0 = gui_with_ui._results_list.controls[0].content.controls[0]
        checkbox_2 = gui_with_ui._results_list.controls[2].content.controls[0]
        initial_0 = checkbox_0.value
        initial_2 = checkbox_2.value
        gui_with_ui._on_row_click(ENTRY_MEDIUM.path)
        assert checkbox_0.value == initial_0
        assert checkbox_2.value == initial_2

    def test_click_updates_totals(self, gui_with_ui: SteamCleanerGUI):
        _populate_list(gui_with_ui, [ENTRY_SMALL])
        assert gui_with_ui._clean_button.disabled is True
        gui_with_ui._on_row_click(ENTRY_SMALL.path)
        assert gui_with_ui._clean_button.disabled is False
