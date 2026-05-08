from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import flet as ft

from steamcleaner.ui.gui.app import SteamCleanerGUI
from steamcleaner.utils.config import get_value, save_value


def _make_fake_page() -> MagicMock:
    page = MagicMock()
    page.theme_mode = None
    page.window = MagicMock()
    page.window.width = 960
    page.window.height = 640
    page.window.left = 100
    page.window.top = 200
    page.window.min_width = 720
    page.window.min_height = 480
    page.window.on_event = None
    page.window.prevent_close = False
    page.window.destroy = AsyncMock()
    page.padding = 0
    page.add = MagicMock()
    return page


def _make_event(event_type: ft.WindowEventType) -> MagicMock:
    event = MagicMock()
    event.type = event_type
    return event


class TestWindowPositionPersistence:
    def test_saves_position_on_close(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)

            page.window.width = 1024
            page.window.height = 768
            page.window.left = 150
            page.window.top = 250

            asyncio.run(gui._on_window_event(_make_event(ft.WindowEventType.CLOSE)))

            assert get_value("window", "width") == "1024"
            assert get_value("window", "height") == "768"
            assert get_value("window", "left") == "150"
            assert get_value("window", "top") == "250"
            page.window.destroy.assert_awaited_once()

    def test_restores_position_on_startup(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("window", "width", "1100")
            save_value("window", "height", "700")
            save_value("window", "left", "300")
            save_value("window", "top", "400")

            page = _make_fake_page()
            SteamCleanerGUI(page)

            assert page.window.width == 1100
            assert page.window.height == 700
            assert page.window.left == 300
            assert page.window.top == 400

    def test_default_size_without_config(self, tmp_path: Path):
        config_path = tmp_path / "missing.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            page = _make_fake_page()
            SteamCleanerGUI(page)

            assert page.window.width == 960
            assert page.window.height == 640

    def test_saves_position_on_moved(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)

            page.window.left = 200
            page.window.top = 300

            asyncio.run(gui._on_window_event(_make_event(ft.WindowEventType.MOVED)))

            assert get_value("window", "left") == "200"
            assert get_value("window", "top") == "300"

    def test_saves_size_on_resized(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)

            page.window.width = 1200
            page.window.height = 800

            asyncio.run(gui._on_window_event(_make_event(ft.WindowEventType.RESIZED)))

            assert get_value("window", "width") == "1200"
            assert get_value("window", "height") == "800"

    def test_ignores_irrelevant_events(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)

            asyncio.run(gui._on_window_event(_make_event(ft.WindowEventType.FOCUS)))

            assert get_value("window", "left") is None


class TestThemePersistence:
    def test_saves_dark_theme(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)
            assert page.theme_mode == ft.ThemeMode.LIGHT
            gui._on_toggle_theme(None)

            assert get_value("ui", "theme") == "dark"

    def test_saves_light_theme(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "dark")
            page = _make_fake_page()
            gui = SteamCleanerGUI(page)
            assert page.theme_mode == ft.ThemeMode.DARK
            gui._on_toggle_theme(None)

            assert get_value("ui", "theme") == "light"

    def test_restores_saved_theme(self, tmp_path: Path):
        config_path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=config_path):
            save_value("ui", "theme", "light")
            page = _make_fake_page()
            SteamCleanerGUI(page)

            assert page.theme_mode == ft.ThemeMode.LIGHT
