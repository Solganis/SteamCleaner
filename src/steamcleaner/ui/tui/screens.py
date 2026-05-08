from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label

from steamcleaner.cleaner.engine import CleanEngine
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.platform.windows import WindowsAdapter
from steamcleaner.scanner.engine import ScanEngine
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import format_size


class ScanScreen(Screen):
    BINDINGS = [
        ("s", "rescan", "Rescan"),
        ("c", "clean", "Clean selected"),
        ("a", "select_all", "Select all"),
        ("n", "select_none", "Deselect all"),
    ]

    def __init__(self):
        super().__init__()
        self._result: ScanResult = ScanResult()
        self._selected: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Scanning...", id="status-label", classes="total-label")
        yield DataTable(id="results-table")
        yield Horizontal(
            Button("Scan", id="btn-scan", variant="default"),
            Button("Select All", id="btn-select-all", variant="default"),
            Button("Clean Selected", id="btn-clean", variant="success"),
            Button("Clean (Dry Run)", id="btn-dry", variant="warning"),
            id="button-bar",
        )
        yield Footer()

    def on_mount(self):
        table = self.query_one("#results-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("  ", "Size", "Category", "Path", "Description")
        self._run_scan()

    def _run_scan(self):
        status = self.query_one("#status-label", Label)
        status.update("Scanning...")

        platform = WindowsAdapter()
        exclusions = ExclusionRegistry()
        engine = ScanEngine(platform, exclusions)
        self._result = engine.scan()
        self._selected.clear()

        table = self.query_one("#results-table", DataTable)
        table.clear()

        for i, entry in enumerate(self._result.entries):
            table.add_row(
                "[ ]",
                format_size(entry.size_bytes),
                entry.category.value,
                str(entry.path),
                entry.description,
                key=str(i),
            )

        total = format_size(self._result.total_bytes)
        count = len(self._result.entries)
        status.update(f"Found {count} items — {total} total")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        idx = int(event.row_key.value)
        table = self.query_one("#results-table", DataTable)
        if idx in self._selected:
            self._selected.discard(idx)
            table.update_cell(event.row_key, table.columns[next(iter(table.columns))].key, "[ ]")
        else:
            self._selected.add(idx)
            table.update_cell(event.row_key, table.columns[next(iter(table.columns))].key, "[x]")
        self._update_selection_status()

    def _update_selection_status(self):
        selected_entries = [self._result.entries[i] for i in self._selected]
        total = sum(e.size_bytes for e in selected_entries)
        status = self.query_one("#status-label", Label)
        all_total = format_size(self._result.total_bytes)
        sel_total = format_size(total)
        status.update(f"Selected {len(self._selected)}/{len(self._result.entries)} items — {sel_total} / {all_total}")

    def _get_selected_result(self) -> ScanResult:
        entries = [self._result.entries[i] for i in sorted(self._selected)]
        return ScanResult(entries=entries)

    def _do_clean(self, *, dry_run: bool):
        if not self._selected:
            self.notify("Nothing selected", severity="warning")
            return

        selected = self._get_selected_result()
        cleaner = CleanEngine(use_trash=True, dry_run=dry_run)
        stats = cleaner.clean(selected)

        if dry_run:
            self.notify(f"[DRY RUN] Would delete {stats.deleted} items ({format_size(stats.bytes_freed)})")
        else:
            self.notify(f"Deleted {stats.deleted} items ({format_size(stats.bytes_freed)})")
            if stats.errors:
                for err in stats.errors:
                    self.notify(f"Error: {err}", severity="error")
            self._run_scan()

    def on_button_pressed(self, event: Button.Pressed):
        match event.button.id:
            case "btn-scan":
                self._run_scan()
            case "btn-select-all":
                self.action_select_all()
            case "btn-clean":
                self._do_clean(dry_run=False)
            case "btn-dry":
                self._do_clean(dry_run=True)

    def action_rescan(self):
        self._run_scan()

    def action_clean(self):
        self._do_clean(dry_run=False)

    def action_select_all(self):
        table = self.query_one("#results-table", DataTable)
        first_col_key = table.columns[next(iter(table.columns))].key
        if len(self._selected) == len(self._result.entries):
            self._selected.clear()
            for i in range(len(self._result.entries)):
                table.update_cell(str(i), first_col_key, "[ ]")
        else:
            self._selected = set(range(len(self._result.entries)))
            for i in range(len(self._result.entries)):
                table.update_cell(str(i), first_col_key, "[x]")
        self._update_selection_status()

    def action_select_none(self):
        table = self.query_one("#results-table", DataTable)
        first_col_key = table.columns[next(iter(table.columns))].key
        self._selected.clear()
        for i in range(len(self._result.entries)):
            table.update_cell(str(i), first_col_key, "[ ]")
        self._update_selection_status()
