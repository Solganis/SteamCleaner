from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any


def _config_dir() -> Path:
    match sys.platform:
        case "win32":
            import os

            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        case _:
            import os

            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "steamcleaner"


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def save_value(section: str, key: str, value: str):
    config = load_config()
    if section not in config:
        config[section] = {}
    config[section][key] = value

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for section_name, section_entries in config.items():
        lines.append(f"[{section_name}]")
        if isinstance(section_entries, dict):
            for key_name, key_value in section_entries.items():
                lines.append(f'{key_name} = "{key_value}"')
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def get_value(section: str, key: str, default: str | None = None) -> str | None:
    config = load_config()
    section_dict = config.get(section, {})
    if isinstance(section_dict, dict):
        return section_dict.get(key, default)
    return default
