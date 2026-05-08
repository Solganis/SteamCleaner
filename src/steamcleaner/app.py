from __future__ import annotations

import steamcleaner.clients.steam  # noqa: F401 — register SteamClient
from steamcleaner.ui.cli import cli


def main():
    cli()
