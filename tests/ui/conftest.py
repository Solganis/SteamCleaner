from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from steamcleaner.ui.gui.app import SteamCleanerGUI


@pytest.fixture
def fake_page() -> MagicMock:
    page = MagicMock()
    page.theme_mode = None
    page.window = MagicMock()
    page.window.width = 1024
    page.window.height = 700
    page.window.left = 100
    page.window.top = 200
    page.window.min_width = 800
    page.window.min_height = 540
    page.window.visible = True
    page.window.on_event = None
    page.padding = 0
    page.add = MagicMock()
    return page


@pytest.fixture
def gui(tmp_path: Path, fake_page: MagicMock) -> SteamCleanerGUI:
    config_path = tmp_path / "config.toml"
    with patch("steamcleaner.utils.config._config_path", return_value=config_path):
        return SteamCleanerGUI(fake_page)
