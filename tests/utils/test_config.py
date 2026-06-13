import sys
from pathlib import Path
from unittest.mock import patch

from assertpy2 import assert_that

from steamcleaner.utils.config import config_dir, get_list, get_value, load_config, save_value


class TestConfigDir:
    def test_win32_uses_appdata(self):
        with patch.object(sys, "platform", "win32"), patch.dict("os.environ", {"APPDATA": "/fake/appdata"}):
            result = config_dir()
            assert_that(result).is_equal_to(Path("/fake/appdata/steamcleaner"))

    def test_linux_uses_xdg(self):
        with patch.object(sys, "platform", "linux"), patch.dict("os.environ", {"XDG_CONFIG_HOME": "/fake/xdg"}):
            result = config_dir()
            assert_that(result).is_equal_to(Path("/fake/xdg/steamcleaner"))

    def test_linux_default_without_xdg(self, tmp_path: Path):
        env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
        with patch.object(sys, "platform", "linux"), patch.dict("os.environ", env, clear=True):
            result = config_dir()
            assert_that(result).is_equal_to(tmp_path / ".config" / "steamcleaner")


class TestConfig:
    def test_load_empty(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert_that(load_config()).is_equal_to({})

    def test_save_and_load(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            assert_that(get_value("ui", "theme")).is_equal_to("dark")

    def test_save_overwrites(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            save_value("ui", "theme", "light")
            assert_that(get_value("ui", "theme")).is_equal_to("light")

    def test_get_default(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert_that(get_value("ui", "theme", "dark")).is_equal_to("dark")

    def test_get_missing_key(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            assert_that(get_value("ui", "missing")).is_none()

    def test_multiple_sections(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("ui", "theme", "dark")
            save_value("clean", "use_trash", "true")
            assert_that(get_value("ui", "theme")).is_equal_to("dark")
            assert_that(get_value("clean", "use_trash")).is_equal_to("true")

    def test_get_value_non_dict_section_returns_default(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text('broken = "not a section"\n', encoding="utf-8")
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            assert_that(get_value("broken", "key", "fallback")).is_equal_to("fallback")

    def test_save_and_get_list(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", ["C:\\Games", "D:\\Library"])
            result = get_list("scan", "custom_paths")
            assert_that(result).is_equal_to(["C:\\Games", "D:\\Library"])

    def test_get_list_empty(self, tmp_path: Path):
        with patch("steamcleaner.utils.config._config_path", return_value=tmp_path / "missing.toml"):
            assert_that(get_list("scan", "custom_paths")).is_equal_to([])

    def test_get_value_returns_default_for_list_key(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", ["C:\\Games"])
            assert_that(get_value("scan", "custom_paths", "fallback")).is_equal_to("fallback")

    def test_get_list_non_dict_section(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        path.write_text('broken = "not a section"\n', encoding="utf-8")
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            assert_that(get_list("broken", "key")).is_equal_to([])

    def test_save_list_empty(self, tmp_path: Path):
        path = tmp_path / "config.toml"
        with patch("steamcleaner.utils.config._config_path", return_value=path):
            save_value("scan", "custom_paths", [])
            assert_that(get_list("scan", "custom_paths")).is_equal_to([])
