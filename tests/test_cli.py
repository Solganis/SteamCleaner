from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import ScanResult
from steamcleaner.ui.cli import cli


def _fake_result(tmp_path: Path) -> ScanResult:
    return ScanResult(
        entries=[
            JunkEntry(
                path=tmp_path / "redist",
                category=JunkCategory.REDISTRIBUTABLE,
                size_bytes=1024 * 1024 * 50,
                client_name="Steam",
                description="Test redist",
            ),
            JunkEntry(
                path=tmp_path / "shader",
                category=JunkCategory.SHADER_CACHE,
                size_bytes=1024 * 100,
                client_name="Steam",
                description="Test shader",
            ),
        ]
    )


def _empty_result() -> ScanResult:
    return ScanResult()


class TestCliScan:
    def test_scan_shows_results(self, tmp_path: Path):
        result = _fake_result(tmp_path)
        with patch("steamcleaner.ui.cli._build_scanner") as mock_build:
            mock_build.return_value.scan.return_value = result
            runner = CliRunner()
            output = runner.invoke(cli, ["scan"])
            assert output.exit_code == 0
            assert "Scanning..." in output.output
            assert "[Steam]" in output.output
            assert "50.0 MB" in output.output
            assert "2 items" in output.output

    def test_scan_empty(self):
        with patch("steamcleaner.ui.cli._build_scanner") as mock_build:
            mock_build.return_value.scan.return_value = _empty_result()
            runner = CliRunner()
            output = runner.invoke(cli, ["scan"])
            assert output.exit_code == 0
            assert "No junk found" in output.output


class TestCliClean:
    def test_clean_dry_run(self, tmp_path: Path):
        result = _fake_result(tmp_path)
        with patch("steamcleaner.ui.cli._build_scanner") as mock_build:
            mock_build.return_value.scan.return_value = result
            runner = CliRunner()
            output = runner.invoke(cli, ["clean", "--dry-run", "--yes"])
            assert output.exit_code == 0
            assert "DRY RUN" in output.output

    def test_clean_empty(self):
        with patch("steamcleaner.ui.cli._build_scanner") as mock_build:
            mock_build.return_value.scan.return_value = _empty_result()
            runner = CliRunner()
            output = runner.invoke(cli, ["clean", "--yes"])
            assert output.exit_code == 0
            assert "Nothing to clean" in output.output

    def test_clean_real_deletes(self, tmp_path: Path):
        target = tmp_path / "redist"
        target.mkdir()
        (target / "file.exe").write_bytes(b"\x00" * 1024)
        result = ScanResult(
            entries=[
                JunkEntry(
                    path=target,
                    category=JunkCategory.REDISTRIBUTABLE,
                    size_bytes=1024,
                    client_name="Steam",
                ),
            ]
        )
        with (
            patch("steamcleaner.ui.cli._build_scanner") as mock_build,
            patch("steamcleaner.ui.cli.CleanEngine") as mock_engine_cls,
        ):
            mock_build.return_value.scan.return_value = result
            mock_engine_cls.return_value.clean.return_value = type(
                "Stats", (), {"deleted": 1, "skipped": 0, "errors": [], "bytes_freed": 1024}
            )()
            runner = CliRunner()
            output = runner.invoke(cli, ["clean", "--no-trash", "--yes"])
            assert output.exit_code == 0
            assert "Deleted: 1" in output.output


class TestCliHelp:
    def test_help(self):
        runner = CliRunner()
        output = runner.invoke(cli, ["--help"])
        assert output.exit_code == 0
        assert "SteamCleaner" in output.output
        assert "scan" in output.output
        assert "clean" in output.output

    def test_scan_help(self):
        runner = CliRunner()
        output = runner.invoke(cli, ["scan", "--help"])
        assert output.exit_code == 0
        assert "Scan for junk" in output.output

    def test_clean_help(self):
        runner = CliRunner()
        output = runner.invoke(cli, ["clean", "--help"])
        assert output.exit_code == 0
        assert "--dry-run" in output.output
        assert "--no-trash" in output.output

    def test_version(self):
        runner = CliRunner()
        output = runner.invoke(cli, ["--version"])
        assert output.exit_code == 0
        assert "0.2.0" in output.output
