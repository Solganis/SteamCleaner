import logging
import logging.handlers
from pathlib import Path

from steamcleaner.utils.config import _config_dir, get_value, save_value

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 3
_ROOT_LOGGER_NAME = "steamcleaner"


def log_file_path() -> Path:
    return _config_dir() / "steamcleaner.log"


def is_logging_enabled() -> bool:
    return get_value("logging", "enabled", "false") == "true"


def setup_logging() -> logging.Logger:
    root_logger = logging.getLogger(_ROOT_LOGGER_NAME)
    if root_logger.handlers:
        return root_logger

    if is_logging_enabled():
        _attach_file_handler(root_logger)
    else:
        root_logger.setLevel(logging.WARNING)

    return root_logger


def set_logging_enabled(enabled: bool):
    save_value("logging", "enabled", "true" if enabled else "false")
    root_logger = logging.getLogger(_ROOT_LOGGER_NAME)

    if enabled and not root_logger.handlers:
        _attach_file_handler(root_logger)
    elif not enabled and root_logger.handlers:
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)


def _attach_file_handler(logger: logging.Logger):
    path = log_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)
    file_handler.setFormatter(formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.info("Logging enabled, file: %s", path)
