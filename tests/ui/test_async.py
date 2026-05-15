import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft

from steamcleaner.cleaner.engine import CleanStats
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
class TestScanTask:
    @staticmethod
    def _mock_scan_with_entries(*entries: JunkEntry):
        mock_engine = MagicMock()

        # noinspection PyUnusedLocal
        def fake_scan(progress=None, on_found=None, cancel=None, custom_paths=None):
            for entry in entries:
                if on_found:
                    on_found(entry)

        mock_engine.scan.side_effect = fake_scan
        return mock_engine

    @staticmethod
    def _run_scan(gui: SteamCleanerGUI, mock_engine: MagicMock):
        gui._cancel_event = threading.Event()
        with (
            patch("steamcleaner.ui.gui.app.ScanEngine", return_value=mock_engine),
            patch("steamcleaner.ui.gui.app.ExclusionRegistry"),
            patch("steamcleaner.platform.create_adapter"),
            patch.object(gui, "_refresh_list"),
        ):
            asyncio.run(gui._scan_task())

    def test_scan_finds_entries(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL, ENTRY_LARGE)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert len(gui_with_ui._result.entries) == 2

    def test_scan_resets_ui(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert gui_with_ui._cancel_event is None
        assert gui_with_ui._scan_button.text == t("scan")
        assert gui_with_ui._progress.opacity == 0

    def test_scan_cancelled(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = MagicMock()

        # noinspection PyUnusedLocal
        def fake_scan(progress=None, on_found=None, cancel=None, custom_paths=None):
            cancel.set()

        mock_engine.scan.side_effect = fake_scan
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert t("stopped", count=0) in gui_with_ui._status.value

    def test_scan_failure(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = MagicMock()
        mock_engine.scan.side_effect = OSError("disk error")
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert gui_with_ui._status.value == t("scan_failed")

    def test_scan_rebuilds_filters(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL, ENTRY_MEDIUM)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        keys = [option.key for option in gui_with_ui._filter_dropdown.options]
        assert "redistributable" in keys
        assert "shader_cache" in keys


# noinspection PyProtectedMember,PyUnresolvedReferences
class TestCleanTask:
    @staticmethod
    def _run_clean(gui: SteamCleanerGUI, entries: list[JunkEntry], stats: CleanStats):
        mock_cleaner = MagicMock()
        mock_cleaner.clean.return_value = stats
        with (
            patch("steamcleaner.ui.gui.app.CleanEngine", return_value=mock_cleaner),
            patch.object(gui, "_refresh_list"),
        ):
            asyncio.run(gui._clean_task(entries))

    def test_clean_removes_entries(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_LARGE])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert len(gui_with_ui._result.entries) == 1
        assert gui_with_ui._result.entries[0] is ENTRY_LARGE

    def test_clean_clears_selected(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_MEDIUM])
        gui_with_ui._selected = {ENTRY_SMALL.path, ENTRY_MEDIUM.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert ENTRY_SMALL.path not in gui_with_ui._selected

    def test_clean_success_snackbar(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        gui_with_ui._page.overlay.append.assert_called_once()

    def test_clean_errors_dialog(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=0, skipped=1, errors=["permission denied: small_redist"])
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        gui_with_ui._page.show_dialog.assert_called_once()

    def test_clean_resets_state(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert gui_with_ui._cleaning is False
        assert gui_with_ui._scan_button.disabled is False
        assert gui_with_ui._progress.opacity == 0


# noinspection PyProtectedMember,PyUnresolvedReferences
class TestOnClean:
    def test_no_selection_returns_early(self, gui: SteamCleanerGUI):
        gui._selected = set()
        gui._on_clean(None)
        gui._page.show_dialog.assert_not_called()

    def test_trash_mode_content(self, gui: SteamCleanerGUI):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="true"):
            gui._on_clean(None)
        dialog = gui._page.show_dialog.call_args[0][0]
        assert isinstance(dialog.content, ft.Text)

    def test_permanent_mode_content(self, gui: SteamCleanerGUI):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="false"):
            gui._on_clean(None)
        dialog = gui._page.show_dialog.call_args[0][0]
        assert isinstance(dialog.content, ft.Column)

    def test_dialog_has_two_actions(self, gui: SteamCleanerGUI):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="true"):
            gui._on_clean(None)
        dialog = gui._page.show_dialog.call_args[0][0]
        assert len(dialog.actions) == 2


# noinspection PyProtectedMember,PyUnresolvedReferences
class TestConfirmClean:
    def test_sets_cleaning_flag(self, gui: SteamCleanerGUI):
        gui._confirm_clean([ENTRY_SMALL])
        assert gui._cleaning is True

    def test_locks_controls(self, gui: SteamCleanerGUI):
        gui._confirm_clean([ENTRY_SMALL])
        assert gui._scan_button.disabled is True
        assert gui._sort_dropdown.disabled is True

    def test_triggers_clean_task(self, gui: SteamCleanerGUI):
        gui._confirm_clean([ENTRY_SMALL])
        gui._page.run_task.assert_called_once_with(gui._clean_task, [ENTRY_SMALL])
