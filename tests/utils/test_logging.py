import logging

import pytest
from assertpy2 import assert_that

from steamcleaner.utils.logging import is_logging_enabled, log_file_path, set_logging_enabled, setup_logging


@pytest.fixture(autouse=True)
def _clean_logger():
    """Remove all handlers from the steamcleaner logger before/after each test."""
    root_logger = logging.getLogger("steamcleaner")
    original_level = root_logger.level
    original_handlers = root_logger.handlers[:]
    for handler in original_handlers:
        handler.close()
        root_logger.removeHandler(handler)
    yield
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    root_logger.setLevel(original_level)


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("steamcleaner.utils.logging.config_dir", lambda: tmp_path)
    monkeypatch.setattr("steamcleaner.utils.logging.get_value", lambda section, key, default=None: default)
    return tmp_path


def test_setup_logging_disabled_by_default(config_dir):
    logger = setup_logging()
    assert_that(logger.level).is_equal_to(logging.WARNING)
    assert_that(logger.handlers).is_length(0)
    assert_that(str(config_dir / "steamcleaner.log")).does_not_exist()


def test_setup_logging_enabled_creates_file(config_dir, monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    logger = setup_logging()
    assert_that(logger.level).is_equal_to(logging.DEBUG)
    assert_that(logger.handlers).is_length(1)
    logger.info("test message")
    logger.handlers[0].flush()
    assert_that(str(config_dir / "steamcleaner.log")).exists()
    content = (config_dir / "steamcleaner.log").read_text(encoding="utf-8")
    assert_that(content).contains("test message")


def test_setup_logging_is_idempotent(config_dir, monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    setup_logging()
    setup_logging()
    root_logger = logging.getLogger("steamcleaner")
    assert_that(root_logger.handlers).is_length(1)


def test_set_logging_enabled_hot_toggle(config_dir, monkeypatch):
    saved_values: dict[str, str] = {}
    monkeypatch.setattr(
        "steamcleaner.utils.logging.save_value",
        lambda section, key, value: saved_values.update({key: value}),
    )
    setup_logging()
    root_logger = logging.getLogger("steamcleaner")
    assert_that(root_logger.handlers).is_length(0)

    set_logging_enabled(True)
    assert_that(saved_values["enabled"]).is_equal_to("true")
    assert_that(root_logger.handlers).is_length(1)
    assert_that(root_logger.level).is_equal_to(logging.DEBUG)

    set_logging_enabled(False)
    assert_that(saved_values["enabled"]).is_equal_to("false")
    assert_that(root_logger.handlers).is_length(0)
    assert_that(root_logger.level).is_equal_to(logging.WARNING)


def test_set_logging_enabled_noop_when_already_enabled(config_dir, monkeypatch):
    monkeypatch.setattr("steamcleaner.utils.logging.save_value", lambda section, key, value: None)
    set_logging_enabled(True)
    root_logger = logging.getLogger("steamcleaner")
    assert_that(root_logger.handlers).is_length(1)
    set_logging_enabled(True)
    assert_that(root_logger.handlers).is_length(1)


def test_log_file_path_location(config_dir):
    assert_that(log_file_path()).is_equal_to(config_dir / "steamcleaner.log")


def test_is_logging_enabled_reads_config(monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    assert_that(is_logging_enabled()).is_true()

    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "false" if key == "enabled" else default,
    )
    assert_that(is_logging_enabled()).is_false()
