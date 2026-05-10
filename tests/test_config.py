import sys
from pathlib import Path
from unittest.mock import patch

from steamcleaner.utils.config import config_dir, get_list, get_value, load_config, save_value


class TestConfigDir:
    def test_win32_uses_appdata(self):
        with patch.object(sys, "platform", "win32"), patch.dict("os.environ", {"APPDATA": "/fake/appdata"}):
            result = config_dir()
            assert result == Path("/fake/appdata/steamcleaner")

    def test_linux_uses_xdg(self):
        with patch.object(sys, "platform", "linux"), patch.dict("os.environ", {"XDG_CONFIG_HOME": "/fake/xdg"}):
            result = config_dir()
            assert result == Path("/fake/xdg/steamcleaner")

    def test_linux_default_without_xdg(self, tmp_path: Path):
        env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
        with patch.object(sys, "platform", "linux"), patch.dict("os.environ", env, clear=True):
            result = config_dir()
            assert result == tmp_path / ".config" / "steamcleaner"


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

    def test_get_value_non_dict_section_returns_default(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text('broken = "not a section"\n', encoding="utf-8")
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            assert get_value("broken", "key", "fallback") == "fallback"

    def test_save_and_get_list(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", ["C:\\Games", "D:\\Library"])
            result = get_list("scan", "custom_paths")
            assert result == ["C:\\Games", "D:\\Library"]

    def test_get_list_empty(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert get_list("scan", "custom_paths") == []

    def test_get_value_returns_default_for_list_key(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", ["C:\\Games"])
            assert get_value("scan", "custom_paths", "fallback") == "fallback"

    def test_get_list_non_dict_section(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text('broken = "not a section"\n', encoding="utf-8")
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            assert get_list("broken", "key") == []

    def test_save_list_empty(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", [])
            assert get_list("scan", "custom_paths") == []
