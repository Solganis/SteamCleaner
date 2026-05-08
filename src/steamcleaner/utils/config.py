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
    with path.open("rb") as f:
        return tomllib.load(f)


def save_value(section: str, key: str, value: str):
    config = load_config()
    if section not in config:
        config[section] = {}
    config[section][key] = value

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    for sec, entries in config.items():
        lines.append(f"[{sec}]")
        if isinstance(entries, dict):
            for k, v in entries.items():
                lines.append(f'{k} = "{v}"')
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def get_value(section: str, key: str, default: str | None = None) -> str | None:
    config = load_config()
    sec = config.get(section, {})
    if isinstance(sec, dict):
        return sec.get(key, default)
    return default
