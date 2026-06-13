from pathlib import Path
from threading import Event, Timer
from unittest.mock import MagicMock, patch

import flet as ft
from assertpy2 import assert_that

from steamcleaner.ui.gui.app import SteamCleanerGUI
from steamcleaner.ui.gui.i18n import t
from steamcleaner.utils.config import get_value, save_value


def _make_event(event_type: ft.WindowEventType) -> MagicMock:
    event = MagicMock()
    event.type = event_type
    return event


# noinspection PyProtectedMember
class TestWindowPositionPersistence:
    def test_saves_position_on_moved(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            gui = SteamCleanerGUI(fake_page)
            gui._initialized = True

            fake_page.window.left = 200
            fake_page.window.top = 300
            fake_page.window.width = 1024
            fake_page.window.height = 768

            gui.on_window_event(_make_event(ft.WindowEventType.MOVED))
            assert isinstance(gui._geometry_save_timer, Timer)
            gui._geometry_save_timer.join()

            assert_that(get_value("window", "left")).is_equal_to("200")
            assert_that(get_value("window", "top")).is_equal_to("300")

    def test_saves_size_on_resized(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            gui = SteamCleanerGUI(fake_page)
            gui._initialized = True

            fake_page.window.width = 1200
            fake_page.window.height = 800
            fake_page.window.left = 100
            fake_page.window.top = 100

            gui.on_window_event(_make_event(ft.WindowEventType.RESIZED))
            assert isinstance(gui._geometry_save_timer, Timer)
            gui._geometry_save_timer.join()

            assert_that(get_value("window", "width")).is_equal_to("1200")
            assert_that(get_value("window", "height")).is_equal_to("800")

    def test_restores_position_on_startup(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("window", "width", "1100")
            save_value("window", "height", "700")
            save_value("window", "left", "300")
            save_value("window", "top", "400")

            SteamCleanerGUI(fake_page)

            assert_that(fake_page.window.width).is_equal_to(1100)
            assert_that(fake_page.window.height).is_equal_to(700)
            assert_that(fake_page.window.left).is_equal_to(300)
            assert_that(fake_page.window.top).is_equal_to(400)

    def test_default_size_without_config(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "missing.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            SteamCleanerGUI(fake_page)

            assert_that(fake_page.window.width).is_equal_to(1024)
            assert_that(fake_page.window.height).is_equal_to(700)

    def test_ignores_irrelevant_events(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            gui = SteamCleanerGUI(fake_page)
            gui._initialized = True

            gui.on_window_event(_make_event(ft.WindowEventType.FOCUS))

            assert_that(get_value("window", "left")).is_none()


class TestThemePersistence:
    def test_saves_dark_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            gui = SteamCleanerGUI(fake_page)
            assert_that(fake_page.theme_mode).is_equal_to(ft.ThemeMode.LIGHT)
            gui.on_toggle_theme(None)

            assert_that(get_value("ui", "theme")).is_equal_to("dark")

    def test_saves_light_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "dark")
            gui = SteamCleanerGUI(fake_page)
            assert_that(fake_page.theme_mode).is_equal_to(ft.ThemeMode.DARK)
            gui.on_toggle_theme(None)

            assert_that(get_value("ui", "theme")).is_equal_to("light")

    def test_restores_saved_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            SteamCleanerGUI(fake_page)

            assert_that(fake_page.theme_mode).is_equal_to(ft.ThemeMode.LIGHT)


# noinspection PyProtectedMember
class TestScanCancelCycles:
    @staticmethod
    def _start_scan(gui: SteamCleanerGUI):
        with patch("threading.Thread"):
            gui.on_scan(None)

    def test_scan_sets_stop_state(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        assert_that(gui._cancel_event).is_not_none()
        assert_that(gui._scan_button.text).is_equal_to(t("stop"))

    def test_second_click_cancels(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        assert isinstance(gui._cancel_event, Event)
        gui.on_scan(None)
        assert_that(gui._cancel_event.is_set()).is_true()

    def test_reset_scan_ui_clears_state(self, gui: SteamCleanerGUI):
        gui._cancel_event = MagicMock()
        gui._reset_scan_ui()

        assert_that(gui._cancel_event).is_none()
        assert_that(gui._scan_button.text).is_equal_to(t("scan"))
        assert_that(gui._progress.opacity).is_equal_to(0)

    def test_multiple_cancel_cycles_keep_working(self, gui: SteamCleanerGUI):
        for cycle in range(5):
            self._start_scan(gui)
            assert isinstance(gui._cancel_event, Event), f"cycle {cycle}: scan should set cancel_event"

            gui.on_scan(None)
            assert_that(gui._cancel_event.is_set()).described_as(
                f"cycle {cycle}: stop should set cancel flag"
            ).is_true()

            gui._reset_scan_ui()
            assert_that(gui._cancel_event).described_as(f"cycle {cycle}: reset should clear cancel_event").is_none()

    def test_scan_after_reset_creates_fresh_event(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        gui.on_scan(None)
        gui._reset_scan_ui()

        self._start_scan(gui)
        assert isinstance(gui._cancel_event, Event)
        assert_that(gui._cancel_event.is_set()).is_false()
        assert_that(gui._scan_button.text).is_equal_to(t("stop"))
