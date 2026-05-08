from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding

from steamcleaner.ui.tui.screens import ScanScreen


class SteamCleanerApp(App):
    TITLE = "SteamCleaner"
    SUB_TITLE = "Reclaim disk space from game clients"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "scan", "Scan"),
    ]
    CSS = """
    Screen {
        background: $surface;
    }
    #header-bar {
        dock: top;
        height: 3;
        background: $primary;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    #results-table {
        height: 1fr;
        margin: 1 2;
    }
    #button-bar {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 1;
    }
    #button-bar Button {
        margin: 0 1;
    }
    .total-label {
        text-style: bold;
        margin: 0 2;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield from []

    def on_mount(self):
        self.push_screen(ScanScreen())

    def action_scan(self):
        self.push_screen(ScanScreen())


def run_tui():
    app = SteamCleanerApp()
    app.run()
