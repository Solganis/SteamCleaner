from __future__ import annotations

import steamcleaner.clients.steam  # noqa: F401
from steamcleaner.ui.gui.app import SteamCleanerGUI


def main(page):
    SteamCleanerGUI(page)
