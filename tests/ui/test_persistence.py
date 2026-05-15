from pathlib import Path
from unittest.mock import MagicMock, patch

import flet as ft

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
            assert gui._geometry_save_timer is not None
            gui._geometry_save_timer.join()

            assert get_value("window", "left") == "200"
            assert get_value("window", "top") == "300"

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
            assert gui._geometry_save_timer is not None
            gui._geometry_save_timer.join()

            assert get_value("window", "width") == "1200"
            assert get_value("window", "height") == "800"

    def test_restores_position_on_startup(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("window", "width", "1100")
            save_value("window", "height", "700")
            save_value("window", "left", "300")
            save_value("window", "top", "400")

            SteamCleanerGUI(fake_page)

            assert fake_page.window.width == 1100
            assert fake_page.window.height == 700
            assert fake_page.window.left == 300
            assert fake_page.window.top == 400

    def test_default_size_without_config(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "missing.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            SteamCleanerGUI(fake_page)

            assert fake_page.window.width == 1024
            assert fake_page.window.height == 700

    def test_ignores_irrelevant_events(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            gui = SteamCleanerGUI(fake_page)
            gui._initialized = True

            gui.on_window_event(_make_event(ft.WindowEventType.FOCUS))

            assert get_value("window", "left") is None


class TestThemePersistence:
    def test_saves_dark_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            gui = SteamCleanerGUI(fake_page)
            assert fake_page.theme_mode == ft.ThemeMode.LIGHT
            gui.on_toggle_theme(None)

            assert get_value("ui", "theme") == "dark"

    def test_saves_light_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "dark")
            gui = SteamCleanerGUI(fake_page)
            assert fake_page.theme_mode == ft.ThemeMode.DARK
            gui.on_toggle_theme(None)

            assert get_value("ui", "theme") == "light"

    def test_restores_saved_theme(self, tmp_path: Path, fake_page: MagicMock):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            SteamCleanerGUI(fake_page)

            assert fake_page.theme_mode == ft.ThemeMode.LIGHT


# noinspection PyProtectedMember
class TestScanCancelCycles:
    @staticmethod
    def _start_scan(gui: SteamCleanerGUI):
        with patch("threading.Thread"):
            gui.on_scan(None)

    def test_scan_sets_stop_state(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        assert gui._cancel_event is not None
        assert gui._scan_button.text == t("stop")

    def test_second_click_cancels(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        assert gui._cancel_event is not None
        gui.on_scan(None)
        assert gui._cancel_event.is_set()

    def test_reset_scan_ui_clears_state(self, gui: SteamCleanerGUI):
        gui._cancel_event = MagicMock()
        gui._reset_scan_ui()

        assert gui._cancel_event is None
        assert gui._scan_button.text == t("scan")
        assert gui._progress.opacity == 0

    def test_multiple_cancel_cycles_keep_working(self, gui: SteamCleanerGUI):
        for cycle in range(5):
            self._start_scan(gui)
            assert gui._cancel_event is not None, f"cycle {cycle}: scan should set cancel_event"

            gui.on_scan(None)
            assert gui._cancel_event.is_set(), f"cycle {cycle}: stop should set cancel flag"

            gui._reset_scan_ui()
            assert gui._cancel_event is None, f"cycle {cycle}: reset should clear cancel_event"

    def test_scan_after_reset_creates_fresh_event(self, gui: SteamCleanerGUI):
        self._start_scan(gui)
        gui.on_scan(None)
        gui._reset_scan_ui()

        self._start_scan(gui)
        assert gui._cancel_event is not None
        assert not gui._cancel_event.is_set()
        assert gui._scan_button.text == t("stop")
