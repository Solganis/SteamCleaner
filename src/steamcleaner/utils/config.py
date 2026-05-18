import logging
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


def config_dir() -> Path:
    match sys.platform:
        case "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        case _:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "steamcleaner"


def _config_path() -> Path:  # pragma: no cover
    return config_dir() / "config.toml"


def load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        _logger.warning("Failed to load config %s: %s", path, exc)
        return {}


def save_value(section: str, key: str, value: str | list[str]) -> None:
    config = load_config()
    if section not in config:
        config[section] = {}
    config[section][key] = value
    _write_config(config)


def save_many(section: str, values: dict[str, str]) -> None:
    config = load_config()
    config.setdefault(section, {})
    config[section].update(values)
    _write_config(config)


def _write_config(config: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for section_name, section_entries in config.items():
        lines.append(f"[{section_name}]")
        if isinstance(section_entries, dict):
            for key_name, key_value in section_entries.items():
                if isinstance(key_value, list):
                    items = ", ".join(f"'{item}'" for item in key_value)
                    lines.append(f"{key_name} = [{items}]")
                else:
                    lines.append(f"{key_name} = '{key_value}'")
        lines.append("")

    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        _logger.error("Failed to write config %s: %s", path, exc)


def get_value(section: str, key: str, default: str | None = None) -> str | None:
    config = load_config()
    section_dict = config.get(section, {})
    if isinstance(section_dict, dict):
        value = section_dict.get(key, default)
        if isinstance(value, list):
            return default
        return value
    return default


def get_list(section: str, key: str) -> list[str]:
    config = load_config()
    section_dict = config.get(section, {})
    if isinstance(section_dict, dict):
        value = section_dict.get(key, [])
        if isinstance(value, list):
            return [str(item) for item in value]
    return []
