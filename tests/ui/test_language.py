from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import flet as ft
import pytest
from assertpy2 import assert_that

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from steamcleaner.ui.gui.app import SteamCleanerGUI

DUMP = JunkEntry(path=Path("C:/Games/crash.dmp"), category=JunkCategory.CRASH_DUMP, size_bytes=10, client_name="Steam")


# test reads protected GUI members
# noinspection PyProtectedMember
class TestLanguageSwitch:
    @pytest.fixture(autouse=True)
    def english_that_is_not_saved(self, monkeypatch):
        monkeypatch.setattr("steamcleaner.ui.gui.i18n._current_lang", "en")
        monkeypatch.setattr("steamcleaner.ui.gui.i18n.save_value", lambda section, key, value: None)

    @staticmethod
    def _switch_to(gui: SteamCleanerGUI, fake_page: MagicMock, language: str) -> None:
        gui._on_settings_click(None)
        row_of_settings = fake_page.show_dialog.call_args[0][0].content.controls[4]
        dropdown = row_of_settings.controls[0]
        assert isinstance(dropdown, ft.Dropdown)
        dropdown.on_select(SimpleNamespace(control=SimpleNamespace(value=language)))

    @staticmethod
    def _cells_of_the_row(gui: SteamCleanerGUI) -> list[ft.Control]:
        row = gui._results_list.controls[0]
        assert isinstance(row, ft.Container)
        assert isinstance(row.content, ft.Row)
        return row.content.controls

    def _texts_of_the_row(self, gui: SteamCleanerGUI) -> tuple[object, object, object]:
        cells = self._cells_of_the_row(gui)
        badge, menu = cells[2], cells[4]
        assert isinstance(badge, ft.Container)
        assert isinstance(badge.content, ft.Text)
        assert isinstance(menu, ft.PopupMenuButton)
        return badge.content.value, menu.items[0].content, menu.items[1].content

    def test_row_listed_before_the_switch_is_shown_in_the_new_language(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock
    ):
        gui_with_ui._result = ScanResult(entries=[DUMP])
        gui_with_ui._refresh_list()
        assert_that(self._texts_of_the_row(gui_with_ui)).is_equal_to(("crash dump", "Open in Explorer", "Copy path"))

        self._switch_to(gui_with_ui, fake_page, "ru")

        assert_that(self._texts_of_the_row(gui_with_ui)).is_equal_to(
            ("дамп падения", "Открыть в проводнике", "Скопировать путь")
        )

    def test_selection_survives_the_switch(self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock):
        gui_with_ui._result = ScanResult(entries=[DUMP])
        gui_with_ui._selected = {DUMP.path}
        gui_with_ui._refresh_list()

        self._switch_to(gui_with_ui, fake_page, "ru")

        checkbox = self._cells_of_the_row(gui_with_ui)[0]
        assert isinstance(checkbox, ft.Checkbox)
        assert_that(checkbox.value).is_true()
