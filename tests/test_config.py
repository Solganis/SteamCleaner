from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from steamcleaner.utils.config import get_value, load_config, save_value


class TestConfig:
    def test_load_empty(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert load_config() == {}

    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            assert get_value("ui", "theme") == "dark"

    def test_save_overwrites(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            save_value("ui", "theme", "light")
            assert get_value("ui", "theme") == "light"

    def test_get_default(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert get_value("ui", "theme", "dark") == "dark"

    def test_get_missing_key(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            assert get_value("ui", "missing") is None

    def test_multiple_sections(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            save_value("clean", "use_trash", "true")
            assert get_value("ui", "theme") == "dark"
            assert get_value("clean", "use_trash") == "true"
