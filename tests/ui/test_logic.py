import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.ui.gui.app import SteamCleanerGUI
from steamcleaner.ui.gui.i18n import t


def _make_entry(
    name: str,
    category: JunkCategory = JunkCategory.REDISTRIBUTABLE,
    size: int = 1024,
    game_root: Path | None = None,
    display_name: str | None = None,
) -> JunkEntry:
    return JunkEntry(
        path=Path(f"C:/Games/{name}"),
        category=category,
        size_bytes=size,
        client_name="Steam",
        game_root=game_root,
        display_name=display_name,
    )


ENTRY_SMALL = _make_entry("small_redist", JunkCategory.REDISTRIBUTABLE, 100)
ENTRY_MEDIUM = _make_entry("medium_shader", JunkCategory.SHADER_CACHE, 5000)
ENTRY_LARGE = _make_entry("large_dump", JunkCategory.CRASH_DUMP, 90000)


# noinspection PyProtectedMember
class TestDisplayPath:
    def test_with_display_name(self):
        entry = _make_entry("file.exe", display_name="Custom Name")
        assert SteamCleanerGUI._display_path(entry) == "Custom Name"

    def test_with_game_root(self):
        entry = _make_entry(
            "TestGame/_CommonRedist/vcredist.exe",
            game_root=Path("C:/Games/TestGame"),
        )
        result = SteamCleanerGUI._display_path(entry)
        assert result == r"TestGame\_CommonRedist\vcredist.exe"

    def test_without_game_root_or_display_name(self):
        entry = _make_entry("some_file.exe")
        assert SteamCleanerGUI._display_path(entry) == str(entry.path)

    def test_game_root_not_parent_of_path(self):
        entry = JunkEntry(
            path=Path("D:/Other/file.exe"),
            category=JunkCategory.REDISTRIBUTABLE,
            size_bytes=100,
            client_name="Steam",
            game_root=Path("C:/Games/TestGame"),
        )
        assert SteamCleanerGUI._display_path(entry) == str(entry.path)

    def test_display_name_takes_priority_over_game_root(self):
        entry = _make_entry(
            "TestGame/file.exe",
            game_root=Path("C:/Games/TestGame"),
            display_name="Override",
        )
        assert SteamCleanerGUI._display_path(entry) == "Override"


# noinspection PyProtectedMember
class TestApplySortFilter:
    @staticmethod
    def _with_entries(gui: SteamCleanerGUI, entries: list[JunkEntry]) -> SteamCleanerGUI:
        gui._result = ScanResult(entries=list(entries))
        return gui

    def test_sort_size_desc(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_LARGE, ENTRY_MEDIUM])
        gui._sort_key = "size_desc"
        gui._apply_sort_filter()
        sizes = [entry.size_bytes for entry in gui._visible_entries]
        assert sizes == [90000, 5000, 100]

    def test_sort_size_asc(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_LARGE, ENTRY_SMALL, ENTRY_MEDIUM])
        gui._sort_key = "size_asc"
        gui._apply_sort_filter()
        sizes = [entry.size_bytes for entry in gui._visible_entries]
        assert sizes == [100, 5000, 90000]

    def test_sort_by_category(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_LARGE, ENTRY_SMALL, ENTRY_MEDIUM])
        gui._sort_key = "category"
        gui._apply_sort_filter()
        categories = [entry.category for entry in gui._visible_entries]
        assert categories == [JunkCategory.CRASH_DUMP, JunkCategory.REDISTRIBUTABLE, JunkCategory.SHADER_CACHE]

    def test_sort_by_path(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_MEDIUM, ENTRY_LARGE, ENTRY_SMALL])
        gui._sort_key = "path"
        gui._apply_sort_filter()
        names = [entry.path.name for entry in gui._visible_entries]
        assert names == ["large_dump", "medium_shader", "small_redist"]

    def test_filter_by_category(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui._category_filter = "shader_cache"
        gui._apply_sort_filter()
        assert len(gui._visible_entries) == 1
        assert gui._visible_entries[0].category == JunkCategory.SHADER_CACHE

    def test_filter_all_shows_everything(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui._category_filter = "all"
        gui._apply_sort_filter()
        assert len(gui._visible_entries) == 3

    def test_search_query(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui._search_query = "shader"
        gui._apply_sort_filter()
        assert len(gui._visible_entries) == 1
        assert gui._visible_entries[0] is ENTRY_MEDIUM

    def test_search_case_insensitive(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM])
        gui._search_query = "SMALL"
        gui._apply_sort_filter()
        assert len(gui._visible_entries) == 1

    def test_filter_and_search_combined(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui._category_filter = "redistributable"
        gui._search_query = "small"
        gui._apply_sort_filter()
        assert len(gui._visible_entries) == 1
        assert gui._visible_entries[0] is ENTRY_SMALL

    def test_no_results_after_filter(self, gui: SteamCleanerGUI):
        gui = self._with_entries(gui, [ENTRY_SMALL])
        gui._category_filter = "crash_dump"
        gui._apply_sort_filter()
        assert gui._visible_entries == []


# noinspection PyProtectedMember
class TestToggleSelection:
    def test_toggle_adds_to_selected(self, gui: SteamCleanerGUI):
        path = Path("C:/Games/test")
        gui._on_toggle(path, True)
        assert path in gui._selected

    def test_toggle_removes_from_selected(self, gui: SteamCleanerGUI):
        path = Path("C:/Games/test")
        gui._selected.add(path)
        gui._on_toggle(path, False)
        assert path not in gui._selected

    def test_toggle_idempotent_remove(self, gui: SteamCleanerGUI):
        path = Path("C:/Games/test")
        gui._on_toggle(path, False)
        assert path not in gui._selected


# noinspection PyProtectedMember
class TestSetControlsLocked:
    def test_locked_disables_controls(self, gui: SteamCleanerGUI):
        gui._set_controls_locked(locked=True)
        assert gui._sort_dropdown.disabled is True
        assert gui._filter_dropdown.disabled is True
        assert gui._search_field.disabled is True
        assert gui._results_list.disabled is True
        assert gui._results_list.opacity == 0.4

    def test_unlocked_enables_controls(self, gui: SteamCleanerGUI):
        gui._set_controls_locked(locked=True)
        gui._set_controls_locked(locked=False)
        assert gui._sort_dropdown.disabled is False
        assert gui._filter_dropdown.disabled is False
        assert gui._search_field.disabled is False
        assert gui._results_list.disabled is False
        assert gui._results_list.opacity == 1.0

    def test_clean_button_disabled_without_selection(self, gui: SteamCleanerGUI):
        gui._set_controls_locked(locked=False)
        assert gui._clean_button.disabled is True

    def test_clean_button_enabled_with_selection(self, gui: SteamCleanerGUI):
        gui._selected.add(Path("C:/Games/test"))
        gui._set_controls_locked(locked=False)
        assert gui._clean_button.disabled is False

    def test_select_all_disabled_without_entries(self, gui: SteamCleanerGUI):
        gui._set_controls_locked(locked=False)
        assert gui._select_all_button.disabled is True

    def test_select_all_enabled_with_entries(self, gui: SteamCleanerGUI):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._set_controls_locked(locked=False)
        assert gui._select_all_button.disabled is False


# noinspection PyProtectedMember
class TestOnKeyboard:
    @staticmethod
    def _make_key_event(key: str, ctrl: bool = False) -> MagicMock:
        event = MagicMock()
        event.key = key
        event.ctrl = ctrl
        event.shift = False
        event.alt = False
        event.meta = False
        return event

    def test_escape_cancels_scan(self, gui: SteamCleanerGUI):
        from threading import Event

        gui._cancel_event = Event()
        gui._on_keyboard(self._make_key_event("Escape"))
        assert gui._cancel_event is not None
        assert gui._cancel_event.is_set()

    def test_escape_clears_selection(self, gui: SteamCleanerGUI):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._visible_entries = [ENTRY_SMALL]
        gui._selected.add(ENTRY_SMALL.path)
        with patch.object(gui, "_refresh_list"):
            gui._on_keyboard(self._make_key_event("Escape"))
        assert len(gui._selected) == 0

    def test_f5_triggers_scan(self, gui: SteamCleanerGUI):
        with patch.object(gui, "on_scan") as mock_scan:
            gui._on_keyboard(self._make_key_event("F5"))
            mock_scan.assert_called_once_with(None)

    def test_f5_blocked_during_cleaning(self, gui: SteamCleanerGUI):
        gui._cleaning = True
        with patch.object(gui, "on_scan") as mock_scan:
            gui._on_keyboard(self._make_key_event("F5"))
            mock_scan.assert_not_called()

    def test_ctrl_a_selects_all(self, gui: SteamCleanerGUI):
        with patch.object(gui, "_on_select_all") as mock_select:
            gui._on_keyboard(self._make_key_event("A", ctrl=True))
            mock_select.assert_called_once_with(None)

    def test_ctrl_a_blocked_during_scan(self, gui: SteamCleanerGUI):
        from threading import Event

        gui._cancel_event = Event()
        with patch.object(gui, "_on_select_all") as mock_select:
            gui._on_keyboard(self._make_key_event("A", ctrl=True))
            mock_select.assert_not_called()

    def test_keys_ignored_when_text_focused(self, gui: SteamCleanerGUI):
        gui._text_input_focused = True
        with patch.object(gui, "on_scan") as mock_scan:
            gui._on_keyboard(self._make_key_event("F5"))
            mock_scan.assert_not_called()

    def test_escape_not_blocked_by_text_focus(self, gui: SteamCleanerGUI):
        gui._text_input_focused = True
        gui._search_field.value = "something"
        with patch.object(gui, "_refresh_list"):
            gui._on_keyboard(self._make_key_event("Escape"))
        assert gui._search_query == ""


# noinspection PyProtectedMember
class TestRebuildFilterOptions:
    @staticmethod
    def _with_entries(gui: SteamCleanerGUI, entries: list[JunkEntry]) -> SteamCleanerGUI:
        gui._result = ScanResult(entries=list(entries))
        return gui

    def test_single_category(self, gui: SteamCleanerGUI):
        self._with_entries(gui, [ENTRY_SMALL])
        gui._rebuild_filter_options()
        keys = [option.key for option in gui._filter_dropdown.options]
        assert keys == ["all", "redistributable"]

    def test_multiple_categories_sorted(self, gui: SteamCleanerGUI):
        self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        gui._rebuild_filter_options()
        keys = [option.key for option in gui._filter_dropdown.options]
        assert keys == ["all", "crash_dump", "redistributable", "shader_cache"]

    def test_empty_entries_only_all(self, gui: SteamCleanerGUI):
        self._with_entries(gui, [])
        gui._rebuild_filter_options()
        assert len(gui._filter_dropdown.options) == 1
        assert gui._filter_dropdown.options[0].key == "all"

    def test_resets_filter_when_category_gone(self, gui: SteamCleanerGUI):
        self._with_entries(gui, [ENTRY_SMALL])
        gui._category_filter = "shader_cache"
        gui._rebuild_filter_options()
        assert gui._category_filter is None
        assert gui._filter_dropdown.value == "all"

    def test_keeps_filter_when_category_present(self, gui: SteamCleanerGUI):
        self._with_entries(gui, [ENTRY_SMALL, ENTRY_MEDIUM])
        gui._category_filter = "shader_cache"
        gui._rebuild_filter_options()
        assert gui._category_filter == "shader_cache"


# noinspection PyProtectedMember
class TestUpdateTotals:
    @staticmethod
    def _with_state(
        gui: SteamCleanerGUI,
        entries: list[JunkEntry],
        selected: set[Path] | None = None,
        visible: list[JunkEntry] | None = None,
    ) -> SteamCleanerGUI:
        gui._result = ScanResult(entries=list(entries))
        gui._selected = selected or set()
        gui._visible_entries = visible if visible is not None else list(entries)
        return gui

    def test_no_selection_disables_clean(self, gui: SteamCleanerGUI):
        self._with_state(gui, [ENTRY_SMALL, ENTRY_LARGE])
        gui._update_totals()
        assert gui._clean_button.disabled is True

    def test_with_selection_enables_clean(self, gui: SteamCleanerGUI):
        self._with_state(gui, [ENTRY_SMALL, ENTRY_LARGE], selected={ENTRY_SMALL.path})
        gui._update_totals()
        assert gui._clean_button.disabled is False

    def test_partial_selection_correct_sum(self, gui: SteamCleanerGUI):
        self._with_state(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE], selected={ENTRY_SMALL.path, ENTRY_MEDIUM.path})
        gui._update_totals()
        expected_selected = ENTRY_SMALL.size_bytes + ENTRY_MEDIUM.size_bytes
        assert str(expected_selected) in gui._total_label.value or "5.0" in gui._total_label.value

    def test_filter_note_when_filtered(self, gui: SteamCleanerGUI):
        self._with_state(gui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE], visible=[ENTRY_SMALL])
        gui._update_totals()
        assert t("total_shown", shown=1) in gui._total_label.value

    def test_empty_result_disables_select_all(self, gui: SteamCleanerGUI):
        self._with_state(gui, [])
        gui._update_totals()
        assert gui._select_all_button.disabled is True


# noinspection PyProtectedMember
class TestUpdateEmptyState:
    def test_visible_entries_hides_state(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._visible_entries = [ENTRY_SMALL]
        gui_with_ui._update_empty_state()
        assert gui_with_ui._empty_state.visible is False

    def test_filtered_out_shows_filter_icon(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._visible_entries = []
        gui_with_ui._update_empty_state()
        assert gui_with_ui._empty_state.visible is True
        assert gui_with_ui._empty_state.controls[1].name == ft.Icons.FILTER_LIST_OFF
        assert gui_with_ui._empty_state.controls[2].value == t("empty_filter")

    def test_no_results_shows_search_icon(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[])
        gui_with_ui._visible_entries = []
        gui_with_ui._update_empty_state()
        assert gui_with_ui._empty_state.visible is True
        assert gui_with_ui._empty_state.controls[1].name == ft.Icons.SEARCH_OFF
        assert gui_with_ui._empty_state.controls[2].value == t("empty_scan")


# noinspection PyProtectedMember
class TestDrainFoundQueue:
    def test_empty_queue_no_change(self, gui_with_ui: SteamCleanerGUI):
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        initial_count = len(gui_with_ui._result.entries)
        gui_with_ui._drain_found_queue(found_queue)
        assert len(gui_with_ui._result.entries) == initial_count

    def test_single_entry_drained(self, gui_with_ui: SteamCleanerGUI):
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        found_queue.put(ENTRY_SMALL)
        gui_with_ui._drain_found_queue(found_queue)
        assert len(gui_with_ui._result.entries) == 1
        assert gui_with_ui._result.entries[0] is ENTRY_SMALL

    def test_multiple_entries_drained(self, gui_with_ui: SteamCleanerGUI):
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        for entry in [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE]:
            found_queue.put(entry)
        gui_with_ui._drain_found_queue(found_queue)
        assert len(gui_with_ui._result.entries) == 3
        assert len(gui_with_ui._results_list.controls) == 3

    def test_rebuilds_filter_options(self, gui_with_ui: SteamCleanerGUI):
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        found_queue.put(ENTRY_SMALL)
        found_queue.put(ENTRY_MEDIUM)
        gui_with_ui._drain_found_queue(found_queue)
        keys = [option.key for option in gui_with_ui._filter_dropdown.options]
        assert "redistributable" in keys
        assert "shader_cache" in keys

    def test_updates_progress_label(self, gui_with_ui: SteamCleanerGUI):
        found_queue: queue.Queue[JunkEntry] = queue.Queue()
        found_queue.put(ENTRY_SMALL)
        gui_with_ui._drain_found_queue(found_queue)
        assert gui_with_ui._total_label.value != ""
