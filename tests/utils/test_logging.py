import logging

import pytest

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
    assert logger.level == logging.WARNING
    assert len(logger.handlers) == 0
    assert not (config_dir / "steamcleaner.log").exists()


def test_setup_logging_enabled_creates_file(config_dir, monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    logger = setup_logging()
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    logger.info("test message")
    logger.handlers[0].flush()
    assert (config_dir / "steamcleaner.log").exists()
    content = (config_dir / "steamcleaner.log").read_text(encoding="utf-8")
    assert "test message" in content


def test_setup_logging_is_idempotent(config_dir, monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    setup_logging()
    setup_logging()
    root_logger = logging.getLogger("steamcleaner")
    assert len(root_logger.handlers) == 1


def test_set_logging_enabled_hot_toggle(config_dir, monkeypatch):
    saved_values: dict[str, str] = {}
    monkeypatch.setattr(
        "steamcleaner.utils.logging.save_value",
        lambda section, key, value: saved_values.update({key: value}),
    )
    setup_logging()
    root_logger = logging.getLogger("steamcleaner")
    assert len(root_logger.handlers) == 0

    set_logging_enabled(True)
    assert saved_values["enabled"] == "true"
    assert len(root_logger.handlers) == 1
    assert root_logger.level == logging.DEBUG

    set_logging_enabled(False)
    assert saved_values["enabled"] == "false"
    assert len(root_logger.handlers) == 0
    assert root_logger.level == logging.WARNING


def test_log_file_path_location(config_dir):
    assert log_file_path() == config_dir / "steamcleaner.log"


def test_is_logging_enabled_reads_config(monkeypatch):
    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "true" if key == "enabled" else default,
    )
    assert is_logging_enabled() is True

    monkeypatch.setattr(
        "steamcleaner.utils.logging.get_value",
        lambda section, key, default=None: "false" if key == "enabled" else default,
    )
    assert is_logging_enabled() is False
