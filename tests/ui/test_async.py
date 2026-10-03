import logging
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import flet as ft
import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter, run_bounded, write_app_manifest

from steamcleaner.cleaner.engine import CleanStats
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.ui.gui.i18n import t

if TYPE_CHECKING:
    import os

    from steamcleaner.ui.gui.app import SteamCleanerGUI


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


# test deliberately accesses a protected member
# noinspection PyProtectedMember
class TestScanTask:
    @staticmethod
    def _mock_scan_with_entries(*entries: JunkEntry):
        mock_engine = MagicMock()

        # parameters match the patched scan() signature; unused in this stub
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
            patch("steamcleaner.ui.gui.app.create_adapter"),
            patch.object(gui, "_refresh_list"),
        ):
            run_bounded(gui._scan_task())

    def test_scan_finds_entries(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL, ENTRY_LARGE)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert_that(gui_with_ui._result.entries).is_length(2)

    def test_scan_resets_ui(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert_that(gui_with_ui._cancel_event).is_none()
        assert_that(gui_with_ui._scan_button.content).is_equal_to(t("scan"))
        assert_that(gui_with_ui._progress.opacity).is_equal_to(0)

    def test_scan_cancelled(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = MagicMock()

        # parameters match the patched scan() signature; unused in this stub
        # noinspection PyUnusedLocal
        def fake_scan(cancel: threading.Event, progress=None, on_found=None, custom_paths=None):
            cancel.set()

        mock_engine.scan.side_effect = fake_scan
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert isinstance(gui_with_ui._status.value, str)
        assert_that(gui_with_ui._status.value).contains(t("stopped", count=0))

    def test_scan_failure(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = MagicMock()
        mock_engine.scan.side_effect = OSError("disk error")
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        assert_that(gui_with_ui._status.value).is_equal_to(t("scan_failed"))

    def test_scan_rebuilds_filters(self, gui_with_ui: SteamCleanerGUI):
        mock_engine = self._mock_scan_with_entries(ENTRY_SMALL, ENTRY_MEDIUM)
        TestScanTask._run_scan(gui_with_ui, mock_engine)
        keys = [option.key for option in gui_with_ui._filter_dropdown.options]
        assert_that(keys).contains("redistributable")
        assert_that(keys).contains("shader_cache")


# test reads protected GUI members and mock attributes that PyCharm does not resolve
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
            run_bounded(gui._clean_task(entries, True, frozenset()))

    def test_clean_removes_entries(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_LARGE])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert_that(gui_with_ui._result.entries).is_length(1)
        assert_that(gui_with_ui._result.entries[0]).is_same_as(ENTRY_LARGE)

    def test_clean_clears_selected(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_MEDIUM])
        gui_with_ui._selected = {ENTRY_SMALL.path, ENTRY_MEDIUM.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert_that(gui_with_ui._selected).does_not_contain(ENTRY_SMALL.path)

    def test_filter_stops_offering_a_category_whose_entries_are_gone(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_LARGE])
        gui_with_ui._rebuild_filter_options()

        self._run_clean(gui_with_ui, [ENTRY_SMALL], CleanStats(deleted=1, bytes_freed=100))

        keys = [option.key for option in gui_with_ui._filter_dropdown.options]
        assert_that(keys).is_equal_to(["all", "crash_dump"])

    def test_clean_success_snackbar(self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        fake_page.overlay.append.assert_called_once()

    def test_permanent_deletion_summary_reports_freed_space(self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        self._run_clean(gui_with_ui, [ENTRY_SMALL], CleanStats(deleted=1, bytes_freed=100))
        snackbar = fake_page.overlay.append.call_args[0][0]
        assert_that(snackbar.content.value).is_equal_to(t("deleted_summary", count=1, size="100 B"))

    def test_trash_summary_does_not_claim_freed_space(self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        self._run_clean(gui_with_ui, [ENTRY_SMALL], CleanStats(deleted=1, trashed=1, bytes_trashed=2048))
        snackbar = fake_page.overlay.append.call_args[0][0]
        assert_that(snackbar.content.value).is_equal_to(t("trashed_summary", count=1, size="2.0 KB"))

    def test_summary_tells_what_was_trashed_from_what_was_deleted_for_good(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock
    ):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE])
        stats = CleanStats(deleted=3, trashed=1, bytes_trashed=2048, bytes_freed=4096)
        self._run_clean(gui_with_ui, [ENTRY_SMALL, ENTRY_MEDIUM, ENTRY_LARGE], stats)
        snackbar = fake_page.overlay.append.call_args[0][0]
        assert_that(snackbar.content.value).is_equal_to(
            "Moved 1 items (2.0 KB) to the trash. Empty it to free the space. Deleted 2 items, freed 4.0 KB"
        )

    def test_summary_of_a_clean_that_removed_nothing_claims_no_trash(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock
    ):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        self._run_clean(gui_with_ui, [ENTRY_SMALL], CleanStats(skipped=1))
        snackbar = fake_page.overlay.append.call_args[0][0]
        assert_that(snackbar.content.value).is_equal_to("Deleted 0 items, freed 0 B")

    def test_clean_errors_dialog(self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=0, skipped=1, errors=["permission denied: small_redist"])
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        fake_page.show_dialog.assert_called_once()

    def test_clean_resets_state(self, gui_with_ui: SteamCleanerGUI):
        gui_with_ui._result = ScanResult(entries=[ENTRY_SMALL])
        gui_with_ui._selected = {ENTRY_SMALL.path}
        stats = CleanStats(deleted=1, bytes_freed=100)
        self._run_clean(gui_with_ui, [ENTRY_SMALL], stats)
        assert_that(gui_with_ui._cleaning).is_false()
        assert_that(gui_with_ui._scan_button.disabled).is_false()
        assert_that(gui_with_ui._progress.opacity).is_equal_to(0)


# test reads protected GUI members
# noinspection PyProtectedMember
class TestCleanTaskWhoseWorkerFails:
    @staticmethod
    def _run(gui: SteamCleanerGUI, entries: list[JunkEntry], failure: Exception, removed: Path | None = None):
        def fail(_result: ScanResult, callback: object) -> CleanStats:
            if removed is not None:
                removed.unlink()
            raise failure

        cleaner = MagicMock()
        cleaner.clean.side_effect = fail
        with (
            patch("steamcleaner.ui.gui.app.CleanEngine", return_value=cleaner),
            patch.object(gui, "_refresh_list") as refresh,
        ):
            run_bounded(gui._clean_task(entries, False, frozenset()))
        return refresh

    @staticmethod
    def _make_entries(tmp_path: Path) -> list[JunkEntry]:
        entries = []
        for name in ("first.dmp", "second.dmp", "untouched.dmp"):
            (tmp_path / name).write_bytes(b"x" * 10)
            entries.append(
                JunkEntry(path=tmp_path / name, category=JunkCategory.CRASH_DUMP, size_bytes=10, client_name="Steam")
            )
        return entries

    @pytest.mark.parametrize(
        "failure",
        [OSError("the device is not ready"), RuntimeError("no adapter"), TypeError("a bug")],
        ids=["OSError", "RuntimeError", "a-bug"],
    )
    def test_task_ends_and_says_the_clean_failed(
        self, gui_with_ui: SteamCleanerGUI, tmp_path: Path, caplog, failure: Exception
    ):
        entries = self._make_entries(tmp_path)
        gui_with_ui._result = ScanResult(entries=list(entries))
        gui_with_ui._confirm_clean(entries[:2], use_trash=False, for_good=frozenset())

        with caplog.at_level(logging.ERROR, logger="steamcleaner.ui.gui.app"):
            refresh = self._run(gui_with_ui, entries[:2], failure)

        assert_that(gui_with_ui._status.value).is_equal_to("Cleaning failed")
        assert_that(gui_with_ui._cleaning).is_false()
        assert_that(gui_with_ui._scan_button.disabled).is_false()
        assert_that(gui_with_ui._sort_dropdown.disabled).is_false()
        assert_that(gui_with_ui._progress.opacity).is_equal_to(0)
        assert_that(gui_with_ui._progress.value).is_none()
        refresh.assert_called_once_with()
        assert_that(caplog.messages).is_equal_to(["Clean failed"])
        assert_that(caplog.records[0].exc_info[1]).is_same_as(failure)

    def test_list_keeps_what_is_still_there_and_drops_what_went_before_the_failure(
        self, gui_with_ui: SteamCleanerGUI, tmp_path: Path
    ):
        first, second, untouched = self._make_entries(tmp_path)
        gui_with_ui._result = ScanResult(entries=[first, second, untouched])
        gui_with_ui._selected = {first.path, second.path}

        self._run(gui_with_ui, [first, second], OSError("the device is not ready"), removed=first.path)

        assert_that(gui_with_ui._result.entries).is_equal_to([second, untouched])
        assert_that(gui_with_ui._selected).is_equal_to({second.path})

    def test_entry_that_was_not_being_cleaned_stays_listed_even_when_its_path_is_gone(
        self, gui_with_ui: SteamCleanerGUI, tmp_path: Path
    ):
        first, second, untouched = self._make_entries(tmp_path)
        gui_with_ui._result = ScanResult(entries=[first, second, untouched])

        self._run(gui_with_ui, [first], OSError("the device is not ready"), removed=untouched.path)

        assert_that(gui_with_ui._result.entries).is_equal_to([first, second, untouched])

    def test_entry_whose_path_cannot_be_inspected_after_the_failure_stays_listed(
        self, gui_with_ui: SteamCleanerGUI, tmp_path: Path, monkeypatch
    ):
        first, second, untouched = self._make_entries(tmp_path)
        gui_with_ui._result = ScanResult(entries=[first, second, untouched])
        real_lstat = Path.lstat

        def deny_the_first(path: Path) -> os.stat_result:
            if path == first.path:
                raise PermissionError(f"Access is denied: {path}")
            return real_lstat(path)

        monkeypatch.setattr(Path, "lstat", deny_the_first)
        monkeypatch.setattr(Path, "exists", lambda path: path != first.path)

        self._run(gui_with_ui, [first, second], OSError("the device is not ready"))

        assert_that(gui_with_ui._result.entries).is_equal_to([first, second, untouched])


# test reads protected GUI members and mock attributes that PyCharm does not resolve
# noinspection PyProtectedMember,PyUnresolvedReferences
class TestOnClean:
    def test_no_selection_returns_early(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        gui._selected = set()
        gui._on_clean(None)
        fake_page.show_dialog.assert_not_called()

    def test_trash_mode_content(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="true"):
            gui._on_clean(None)
        dialog = fake_page.show_dialog.call_args[0][0]
        assert_that(dialog.content).is_instance_of(ft.Text)

    def test_permanent_mode_content(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="false"):
            gui._on_clean(None)
        dialog = fake_page.show_dialog.call_args[0][0]
        assert_that(dialog.content).is_instance_of(ft.Column)

    @pytest.mark.parametrize("use_trash", ["true", "false"], ids=["trash", "permanent"])
    def test_dialog_warns_about_saves_when_leftovers_are_selected(
        self, gui: SteamCleanerGUI, fake_page: MagicMock, use_trash: str
    ):
        leftovers = [_make_entry(name, JunkCategory.LEFTOVER, 700000) for name in ("Old Game", "Older Game")]
        gui._result = ScanResult(entries=[ENTRY_SMALL, *leftovers])
        gui._selected = {entry.path for entry in gui._result.entries}
        with patch("steamcleaner.ui.gui.app.get_value", return_value=use_trash):
            gui._on_clean(None)

        usual_content, warning = fake_page.show_dialog.call_args[0][0].content.controls
        assert_that(warning.value).is_equal_to(
            "2 of them are folders left by uninstalled games. They may hold saves and settings."
        )
        assert_that(usual_content).is_instance_of(ft.Text if use_trash == "true" else ft.Column)

    WARNING = "The trash is not expected to keep {}. Those it refuses will be deleted permanently:"

    @staticmethod
    def _open(gui: SteamCleanerGUI, fake_page: MagicMock, entries: list[JunkEntry], platform: FakePlatformAdapter):
        gui._result = ScanResult(entries=entries)
        gui._selected = {entry.path for entry in entries}
        with (
            patch("steamcleaner.ui.gui.app.get_value", return_value="true"),
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
        ):
            gui._on_clean(None)
        return fake_page.show_dialog.call_args[0][0]

    @staticmethod
    def _lines(block: ft.Column) -> list[str]:
        return [line.value for line in block.controls if isinstance(line, ft.Text)]

    def test_dialog_tells_what_goes_to_the_trash_from_what_the_trash_is_not_expected_to_keep(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        entries = [ENTRY_SMALL, ENTRY_MEDIUM]
        platform = FakePlatformAdapter()
        platform.lose_trash_under(ENTRY_SMALL.path)

        dialog = self._open(gui, fake_page, entries, platform)

        to_trash, not_kept = dialog.content.controls
        assert_that(to_trash.value).is_equal_to("Move 1 items (4.9 KB) to trash?")
        assert_that(self._lines(not_kept)).is_equal_to([self.WARNING.format("1 items (100 B)"), str(ENTRY_SMALL.path)])
        assert_that(dialog.actions[1].content).is_equal_to("Delete")

        dialog.actions[1].on_click(None)

        fake_page.run_task.assert_called_once_with(gui._clean_task, entries, True, frozenset({ENTRY_SMALL.path}))

    def test_dialog_for_a_selection_the_trash_keeps_none_of_does_not_speak_of_a_move(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        entries = [ENTRY_SMALL, ENTRY_MEDIUM]
        platform = FakePlatformAdapter()
        platform.lose_trash_under(Path("C:/Games"))

        dialog = self._open(gui, fake_page, entries, platform)

        assert_that(self._lines(dialog.content)).is_equal_to(
            [self.WARNING.format("2 items (5.0 KB)"), str(ENTRY_SMALL.path), str(ENTRY_MEDIUM.path)]
        )
        assert_that(dialog.actions[1].content).is_equal_to("Delete permanently")

        dialog.actions[1].on_click(None)

        fake_page.run_task.assert_called_once_with(
            gui._clean_task, entries, True, frozenset({ENTRY_SMALL.path, ENTRY_MEDIUM.path})
        )

    def test_dialog_lists_five_of_the_paths_and_counts_the_rest(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        entries = [_make_entry(f"dump{number}.dmp", JunkCategory.CRASH_DUMP, 10) for number in range(7)]
        platform = FakePlatformAdapter()
        platform.lose_trash_under(Path("C:/Games"))

        dialog = self._open(gui, fake_page, entries, platform)

        assert_that(self._lines(dialog.content)[1:]).is_equal_to(
            [*(str(entry.path) for entry in entries[:5]), "and 2 more"]
        )

    def test_dialog_lists_exactly_five_paths_without_a_count_of_the_rest(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        entries = [_make_entry(f"dump{number}.dmp", JunkCategory.CRASH_DUMP, 10) for number in range(5)]
        platform = FakePlatformAdapter()
        platform.lose_trash_under(Path("C:/Games"))

        dialog = self._open(gui, fake_page, entries, platform)

        assert_that(self._lines(dialog.content)[1:]).is_equal_to([str(entry.path) for entry in entries])

    def test_entry_inside_a_folder_the_trash_would_not_keep_is_listed_with_that_folder(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        folder = _make_entry("Big", JunkCategory.REDISTRIBUTABLE, 5000)
        inside = _make_entry("Big/crash.dmp", JunkCategory.CRASH_DUMP, 100)
        entries = [ENTRY_SMALL, inside, folder]
        platform = FakePlatformAdapter()
        platform.trash_capacity = 1000

        dialog = self._open(gui, fake_page, entries, platform)

        to_trash, not_kept = dialog.content.controls
        assert_that(to_trash.value).is_equal_to("Move 1 items (100 B) to trash?")
        assert_that(self._lines(not_kept)).is_equal_to(
            [self.WARNING.format("2 items (4.9 KB)"), str(inside.path), str(folder.path)]
        )

        dialog.actions[1].on_click(None)

        fake_page.run_task.assert_called_once_with(
            gui._clean_task, entries, True, frozenset({inside.path, folder.path})
        )

    def test_dialog_lists_paths_so_that_two_games_of_one_name_are_told_apart(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        entries = [
            JunkEntry(
                path=Path(f"{drive}:/SteamLibrary/steamapps/common/Old Game"),
                category=JunkCategory.LEFTOVER,
                size_bytes=700,
                client_name="Steam",
                display_name="Old Game",
            )
            for drive in ("C", "D")
        ]
        platform = FakePlatformAdapter()
        platform.lose_trash_under(Path("C:/SteamLibrary"))
        platform.lose_trash_under(Path("D:/SteamLibrary"))

        dialog = self._open(gui, fake_page, entries, platform)

        not_kept, _saves = dialog.content.controls
        assert_that(self._lines(not_kept)[1:]).is_equal_to([str(entry.path) for entry in entries])

    def test_entry_reached_through_another_spelling_of_the_folder_is_listed_with_that_folder(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        folder = _make_entry("Big", JunkCategory.REDISTRIBUTABLE, 5000)
        inside = JunkEntry(
            path=Path("M:/mounted/Big/crash.dmp"), category=JunkCategory.CRASH_DUMP, size_bytes=100, client_name="Steam"
        )
        entries = [ENTRY_SMALL, inside, folder]
        platform = FakePlatformAdapter()
        platform.trash_capacity = 1000

        def resolve(path: Path) -> str:
            return str(folder.path / "crash.dmp") if path == inside.path else str(path)

        with patch("steamcleaner.ui.gui.app.os.path.realpath", side_effect=resolve):
            dialog = self._open(gui, fake_page, entries, platform)

        to_trash, not_kept = dialog.content.controls
        assert_that(to_trash.value).is_equal_to("Move 1 items (100 B) to trash?")
        assert_that(self._lines(not_kept)[1:]).is_equal_to([str(inside.path), str(folder.path)])

        dialog.actions[1].on_click(None)

        fake_page.run_task.assert_called_once_with(
            gui._clean_task, entries, True, frozenset({inside.path, folder.path})
        )

    def test_dialog_warns_about_an_item_too_big_for_the_trash(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        platform = FakePlatformAdapter()
        platform.trash_capacity = ENTRY_MEDIUM.size_bytes - 1

        dialog = self._open(gui, fake_page, [ENTRY_SMALL, ENTRY_MEDIUM], platform)

        to_trash, not_kept = dialog.content.controls
        assert_that(to_trash.value).is_equal_to("Move 1 items (100 B) to trash?")
        assert_that(self._lines(not_kept)).is_equal_to(
            [self.WARNING.format("1 items (4.9 KB)"), str(ENTRY_MEDIUM.path)]
        )

    def test_leftover_the_trash_is_not_expected_to_keep_gets_both_warnings(
        self, gui: SteamCleanerGUI, fake_page: MagicMock
    ):
        leftover = _make_entry("Old Game", JunkCategory.LEFTOVER, 700)
        platform = FakePlatformAdapter()
        platform.lose_trash_under(leftover.path)

        dialog = self._open(gui, fake_page, [leftover], platform)

        not_kept, saves = dialog.content.controls
        assert_that(self._lines(not_kept)).is_equal_to([self.WARNING.format("1 items (700 B)"), str(leftover.path)])
        assert_that(saves.value).is_equal_to(
            "1 of them are folders left by uninstalled games. They may hold saves and settings."
        )

    def test_permanent_mode_names_no_path_and_hands_the_mode_on(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        platform = FakePlatformAdapter()
        platform.lose_trash_under(ENTRY_SMALL.path)
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with (
            patch("steamcleaner.ui.gui.app.get_value", return_value="false"),
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
        ):
            gui._on_clean(None)
        delete = fake_page.show_dialog.call_args[0][0].actions[1]
        delete.on_click(None)

        assert_that(delete.content).is_equal_to("Delete permanently")
        fake_page.run_task.assert_called_once_with(gui._clean_task, [ENTRY_SMALL], False, frozenset())

    def test_permanent_mode_dialog_does_not_speak_of_the_trash(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        platform = FakePlatformAdapter()
        platform.lose_trash_under(ENTRY_SMALL.path)
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with (
            patch("steamcleaner.ui.gui.app.get_value", return_value="false"),
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
        ):
            gui._on_clean(None)

        header, warning = fake_page.show_dialog.call_args[0][0].content.controls
        assert_that(header).is_instance_of(ft.Row)
        assert_that(warning.value).is_equal_to("1 items (100 B) will be deleted permanently. This cannot be undone.")

    def test_dialog_has_two_actions(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        gui._result = ScanResult(entries=[ENTRY_SMALL])
        gui._selected = {ENTRY_SMALL.path}
        with patch("steamcleaner.ui.gui.app.get_value", return_value="true"):
            gui._on_clean(None)
        dialog = fake_page.show_dialog.call_args[0][0]
        assert_that(dialog.actions).is_length(2)


# test reads protected GUI members and mock attributes that PyCharm does not resolve
# noinspection PyProtectedMember,PyUnresolvedReferences
class TestConfirmClean:
    def test_sets_cleaning_flag(self, gui: SteamCleanerGUI):
        gui._confirm_clean([ENTRY_SMALL], use_trash=True, for_good=frozenset())
        assert_that(gui._cleaning).is_true()

    def test_locks_controls(self, gui: SteamCleanerGUI):
        gui._confirm_clean([ENTRY_SMALL], use_trash=True, for_good=frozenset())
        assert_that(gui._scan_button.disabled).is_true()
        assert_that(gui._sort_dropdown.disabled).is_true()

    def test_triggers_clean_task(self, gui: SteamCleanerGUI, fake_page: MagicMock):
        gui._confirm_clean([ENTRY_SMALL], use_trash=False, for_good=frozenset({ENTRY_SMALL.path}))
        fake_page.run_task.assert_called_once_with(gui._clean_task, [ENTRY_SMALL], False, frozenset({ENTRY_SMALL.path}))


# test reads protected GUI members
# noinspection PyProtectedMember
class TestCleanTaskKeepsWhatItDidNotRemove:
    def test_entry_the_clean_left_where_it_was_stays_listed_and_selected(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock, tmp_path: Path
    ):
        entries = []
        for name in ("refused", "removed", "untouched"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "setup.exe").write_bytes(b"x" * 2048)
            entries.append(
                JunkEntry(
                    path=tmp_path / name, category=JunkCategory.REDISTRIBUTABLE, size_bytes=2048, client_name="Custom"
                )
            )
        refused, removed, untouched = entries
        gui_with_ui._result = ScanResult(entries=list(entries))
        gui_with_ui._selected = {refused.path, removed.path}
        platform = FakePlatformAdapter(home_dir=tmp_path)
        platform.lose_trash_under(refused.path)
        with (
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
            patch("steamcleaner.platform.base.send2trash", side_effect=shutil.rmtree),
            patch.object(gui_with_ui, "_refresh_list"),
        ):
            run_bounded(gui_with_ui._clean_task([refused, removed], True, frozenset()))

        assert_that(gui_with_ui._result.entries).is_equal_to([refused, untouched])
        assert_that(gui_with_ui._selected).is_equal_to({refused.path})
        assert_that(gui_with_ui._status.value).is_equal_to("2 items remaining, 1 failed")
        assert_that([refused.path.exists(), removed.path.exists()]).is_equal_to([True, False])

    def test_entry_that_was_already_gone_leaves_the_list(self, gui_with_ui: SteamCleanerGUI, tmp_path: Path):
        gone = JunkEntry(
            path=tmp_path / "gone", category=JunkCategory.REDISTRIBUTABLE, size_bytes=2048, client_name="Custom"
        )
        gui_with_ui._result = ScanResult(entries=[gone])
        gui_with_ui._selected = {gone.path}
        with (
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=FakePlatformAdapter(home_dir=tmp_path)),
            patch.object(gui_with_ui, "_refresh_list"),
        ):
            run_bounded(gui_with_ui._clean_task([gone], False, frozenset()))

        assert_that(gui_with_ui._result.entries).is_empty()
        assert_that(gui_with_ui._selected).is_empty()


# test reads protected GUI members
# noinspection PyProtectedMember
class TestCleanTaskChecksLeftoversAgain:
    @staticmethod
    def _make_leftover(tmp_path: Path) -> tuple[Path, JunkEntry]:
        library = tmp_path / "Steam"
        for directory_name in ("Installed Game", "Old Game"):
            game_dir = library / "steamapps" / "common" / directory_name
            game_dir.mkdir(parents=True)
            (game_dir / "data.bin").write_bytes(b"\x00" * 3000)
        write_app_manifest(library, 10, "Installed Game")
        old_game = library / "steamapps" / "common" / "Old Game"
        return library, JunkEntry(path=old_game, category=JunkCategory.LEFTOVER, size_bytes=3000, client_name="Steam")

    @staticmethod
    def _clean_for_real(gui: SteamCleanerGUI, library: Path, entry: JunkEntry) -> MagicMock:
        gui._result = ScanResult(entries=[entry])
        platform = FakePlatformAdapter(install_path=library, home_dir=library.parent)
        with (
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
            patch("steamcleaner.platform.base.send2trash") as mock_trash,
            patch.object(gui, "_refresh_list"),
        ):
            run_bounded(gui._clean_task([entry], False, frozenset()))
        return mock_trash

    def test_leftover_nothing_has_claimed_since_the_scan_is_removed(self, gui_with_ui: SteamCleanerGUI, tmp_path: Path):
        library, leftover = self._make_leftover(tmp_path)

        mock_trash = self._clean_for_real(gui_with_ui, library, leftover)

        mock_trash.assert_not_called()
        assert_that(str(leftover.path)).does_not_exist()

    @pytest.mark.parametrize("warned", [True, False], ids=["warned", "not-warned"])
    def test_item_the_trash_would_not_keep_is_deleted_for_good_only_when_the_dialog_said_so(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock, tmp_path: Path, warned: bool
    ):
        junk = tmp_path / "redist"
        junk.mkdir()
        (junk / "setup.exe").write_bytes(b"x" * 2048)
        entry = JunkEntry(path=junk, category=JunkCategory.REDISTRIBUTABLE, size_bytes=2048, client_name="Custom")
        gui_with_ui._result = ScanResult(entries=[entry])
        platform = FakePlatformAdapter(home_dir=tmp_path)
        platform.lose_trash_under(tmp_path)
        with (
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
            patch("steamcleaner.platform.base.send2trash") as mock_trash,
            patch.object(gui_with_ui, "_refresh_list"),
        ):
            run_bounded(gui_with_ui._clean_task([entry], True, frozenset({junk} if warned else ())))

        mock_trash.assert_not_called()
        assert_that(junk.exists()).is_equal_to(not warned)
        if warned:
            snackbar = fake_page.overlay.append.call_args[0][0]
            assert_that(snackbar.content.value).is_equal_to("Deleted 1 items, freed 2.0 KB")
        else:
            dialog = fake_page.show_dialog.call_args[0][0]
            assert_that([line.value for line in dialog.content.controls]).is_equal_to(
                [f"Skipped, the trash would not keep it: {junk}"]
            )

    def test_file_selected_with_the_folder_that_holds_it_meets_the_fate_the_dialog_showed(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock, tmp_path: Path
    ):
        folder = tmp_path / "Big"
        folder.mkdir()
        (folder / "data.bin").write_bytes(b"x" * 5000)
        (folder / "crash.dmp").write_bytes(b"x" * 100)
        entries = [
            JunkEntry(
                path=folder / "crash.dmp", category=JunkCategory.CRASH_DUMP, size_bytes=100, client_name="Custom"
            ),
            JunkEntry(path=folder, category=JunkCategory.REDISTRIBUTABLE, size_bytes=5100, client_name="Custom"),
        ]
        platform = FakePlatformAdapter(home_dir=tmp_path)
        platform.trash_capacity = 1000
        gui_with_ui._result = ScanResult(entries=entries)
        gui_with_ui._selected = {entry.path for entry in entries}
        with (
            patch("steamcleaner.ui.gui.app.create_adapter", return_value=platform),
            patch("steamcleaner.ui.gui.app.get_value", return_value="true"),
            patch("steamcleaner.platform.base.send2trash") as mock_trash,
            patch.object(gui_with_ui, "_refresh_list"),
        ):
            gui_with_ui._on_clean(None)
            dialog = fake_page.show_dialog.call_args[0][0]
            dialog.actions[1].on_click(None)
            task, *arguments = fake_page.run_task.call_args[0]
            run_bounded(task(*arguments))

        assert_that(dialog.actions[1].content).is_equal_to("Delete permanently")
        assert_that([line.value for line in dialog.content.controls]).is_equal_to(
            [
                "The trash is not expected to keep 2 items (5.0 KB). Those it refuses will be deleted permanently:",
                str(folder / "crash.dmp"),
                str(folder),
            ]
        )
        mock_trash.assert_not_called()
        assert_that(str(folder)).does_not_exist()
        snackbar = fake_page.overlay.append.call_args[0][0]
        assert_that(snackbar.content.value).is_equal_to("Deleted 2 items, freed 5.0 KB")

    def test_leftover_a_game_was_installed_into_after_the_scan_is_kept(
        self, gui_with_ui: SteamCleanerGUI, fake_page: MagicMock, tmp_path: Path
    ):
        library, leftover = self._make_leftover(tmp_path)
        write_app_manifest(library, 20, "Old Game")

        self._clean_for_real(gui_with_ui, library, leftover)

        assert_that(str(leftover.path / "data.bin")).exists()
        dialog = fake_page.show_dialog.call_args[0][0]
        assert_that([line.value for line in dialog.content.controls]).is_equal_to(
            [f"Skipped, no longer confirmed as junk: {leftover.path}"]
        )
