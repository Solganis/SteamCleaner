import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter, serialize_vdf

from steamcleaner.clients.steam import SteamClient
from steamcleaner.clients.steam_scripts import (
    GameScripts,
    InstallerEvidence,
    InstallStep,
    collect_installer_evidence,
    read_game_scripts,
)
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.scanner.exclusions import ExclusionRegistry

if TYPE_CHECKING:
    from steamcleaner.utils.vdf import VdfDict

HIVE = "HKEY_LOCAL_MACHINE\\"
DOTNET_PROGRAM = r"%INSTALLDIR%\DotNetCore\windowsdesktop-runtime-6.0.11-win-x64.exe"
DOTNET_KEY = r"Software\Valve\Steam\Apps\BG3_DotNetCore6011"
DOTNET_STEP: VdfDict = {
    "HasRunKey": HIVE + DOTNET_KEY,
    "process 1": DOTNET_PROGRAM,
    "command 1": "/silent",
    "NoCleanUp": "1",
}
DOTNET_SCRIPT: VdfDict = {"Run Process": {"DotNetCore": DOTNET_STEP}}
ANTICHEAT_PROGRAM = r"%INSTALLDIR%\EAAntiCheat\EAAntiCheat.Installer.exe"
ANTICHEAT_RUN_STEPS: VdfDict = {"EAAntiCheatInstall": {"Process 1": ANTICHEAT_PROGRAM, "Command 1": "--noui --install"}}
ANTICHEAT_SCRIPT: VdfDict = {
    "Run Process": ANTICHEAT_RUN_STEPS,
    "Run Process On Uninstall": {
        "EAAntiCheatInstall": {"Process 1": ANTICHEAT_PROGRAM, "Command 1": "--noui --uninstall"}
    },
}
URL_PROGRAM = r"%INSTALLDIR%\Tools_Builds\AoEURLInstaller_Steam.exe"
URL_KEY = r"Software\Valve\Steam\Apps\813780\URLInstaller\4"
URL_SCRIPT: VdfDict = {
    "Run Process": {"URLInstaller": {"HasRunKey": HIVE + URL_KEY, "process 1": URL_PROGRAM, "command 1": "install"}},
    "Run Process On Uninstall": {"URLProtocol": {"process 1": URL_PROGRAM, "command 1": "uninstall"}},
}
SETUP_PROGRAM = r"%INSTALLDIR%\redist\setup.exe"
SETUP_KEY = r"Software\Valve\Steam\Apps\4242"
RECORDED_SETUP = f'"Setup" {{ "HasRunKey" "{HIVE}{SETUP_KEY}" "process 1" "{SETUP_PROGRAM}" }}'.replace("\\", "\\\\")
UNRECORDED_SETUP = f'"Setup" {{ "process 1" "{SETUP_PROGRAM}" }}'.replace("\\", "\\\\")


def _in_game(game_dir: Path, windows_relative_path: str) -> Path:
    relative = windows_relative_path.removeprefix("%INSTALLDIR%\\")
    return game_dir.joinpath(*PureWindowsPath(relative).parts)


def _write_manifest(library: Path, app_id: int, app_state: VdfDict) -> Path:
    manifest_path = library / "steamapps" / f"appmanifest_{app_id}.acf"
    manifest_path.write_text(serialize_vdf({"AppState": app_state}), encoding="utf-8")
    return manifest_path


def _install_game(
    library: Path, install_dir: str, scripts: dict[str, VdfDict | str], files: dict[str, int] | None = None
) -> Path:
    """Write an app manifest, its scripts and the listed files. A dict script becomes an `InstallScript` body."""
    game_dir = library / "steamapps" / "common" / install_dir
    game_dir.mkdir(parents=True)
    for windows_relative_path, size in (files or {}).items():
        target = _in_game(game_dir, windows_relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00" * size)
    for script_name, script in scripts.items():
        script_path = _in_game(game_dir, script_name)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        text = script if isinstance(script, str) else serialize_vdf({"InstallScript": script})
        script_path.write_text(text, encoding="utf-8")
    listed_scripts: VdfDict = {str(1000 + index): name for index, name in enumerate(scripts)}
    app_state: VdfDict = {
        "appid": "7",
        "name": install_dir,
        "installdir": install_dir,
        "InstallScripts": listed_scripts,
    }
    _write_manifest(library, len(install_dir), app_state)
    return game_dir


def _recorded(*records: tuple[str, str], has_registry: bool = True) -> FakePlatformAdapter:
    platform = FakePlatformAdapter(has_registry=has_registry)
    for subkey, step_name in records:
        platform.set_registry_dword("HKLM", subkey, step_name, 1)
    return platform


@pytest.fixture
def library(tmp_path: Path) -> Path:
    steam = tmp_path / "Steam"
    (steam / "steamapps" / "common").mkdir(parents=True)
    return steam


class TestCompletionRecord:
    def test_step_with_its_record_makes_its_installer_finished(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})
        )

    def test_step_with_no_record_keeps_its_installer(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, DOTNET_PROGRAM)}), finished={})
        )

    def test_record_under_another_value_name_does_not_count(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "SomeOtherStep")))

        assert_that(evidence.needed).is_equal_to(frozenset({_in_game(game_dir, DOTNET_PROGRAM)}))

    @pytest.mark.parametrize(
        ("recorded", "minimum", "finished"),
        [(1, "2", False), (2, "2", True), (3, "2", True), (0, "0", False), (1, "0", True), (7, "0007", True)],
    )
    def test_record_has_to_reach_the_minimum_the_step_asks_for(
        self, library: Path, recorded: int, minimum: str, finished: bool
    ):
        script: VdfDict = {"Run Process": {"DotNetCore": {**DOTNET_STEP, "MinimumHasRunValue": minimum}}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})
        platform = FakePlatformAdapter()
        platform.set_registry_dword("HKLM", DOTNET_KEY, "DotNetCore", recorded)

        evidence = collect_installer_evidence(library, platform)

        installer = _in_game(game_dir, DOTNET_PROGRAM)
        assert_that(installer in evidence.finished).is_equal_to(finished)
        assert_that(installer in evidence.needed).is_equal_to(not finished)

    @pytest.mark.parametrize(
        "minimum",
        ["+1", " 1 ", "1.0", "one", "", "00000000001", "1" * 5000, "\u0661", {"nested": "1"}],
        ids=["signed", "padded", "decimal", "word", "empty", "eleven-digits", "huge", "arabic-digit", "section"],
    )
    def test_minimum_that_is_not_a_plain_number_keeps_the_installer(self, library: Path, minimum: str | VdfDict):
        script: VdfDict = {"Run Process": {"DotNetCore": {**DOTNET_STEP, "MinimumHasRunValue": minimum}}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})
        platform = FakePlatformAdapter()
        platform.set_registry_dword("HKLM", DOTNET_KEY, "DotNetCore", 4_000_000_000)

        evidence = collect_installer_evidence(library, platform)

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, DOTNET_PROGRAM)}), finished={})
        )

    def test_step_without_a_has_run_key_keeps_its_installer(self, library: Path):
        script: VdfDict = {"Run Process": ANTICHEAT_RUN_STEPS}
        game_dir = _install_game(library, "Battlefield 6", {"installScript.vdf": script})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, ANTICHEAT_PROGRAM)}), finished={})
        )

    def test_uninstall_step_keeps_an_installer_whose_run_step_has_its_record(self, library: Path):
        game_dir = _install_game(library, "AoE2DE", {"813780_install.vdf": URL_SCRIPT})

        evidence = collect_installer_evidence(library, _recorded((URL_KEY, "URLInstaller")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, URL_PROGRAM)}), finished={})
        )

    def test_uninstall_step_keeps_its_installer_even_with_a_record_of_its_own(self, library: Path):
        script: VdfDict = {"Run Process On Uninstall": {"DotNetCore": DOTNET_STEP}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, DOTNET_PROGRAM)}), finished={})
        )

    def test_installer_named_by_a_recorded_and_an_unrecorded_step_is_kept(self, library: Path):
        repair_step: VdfDict = {"HasRunKey": HIVE + DOTNET_KEY, "process 1": DOTNET_PROGRAM}
        script: VdfDict = {"Run Process": {"DotNetCore": DOTNET_STEP, "DotNetCoreRepair": repair_step}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, DOTNET_PROGRAM)}), finished={})
        )

    def test_every_numbered_program_of_a_step_is_sorted(self, library: Path):
        second_program = r"%INSTALLDIR%\DotNetCore\aspnetcore-runtime.exe"
        tenth_program = r"%INSTALLDIR%/DotNetCore/hosting-bundle.exe"
        step: VdfDict = {**DOTNET_STEP, "process 2": f'"{second_program}"', "PROCESS 10": tenth_program}
        game_dir = _install_game(
            library, "Baldurs Gate 3", {"InstallScript.vdf": {"Run Process": {"DotNetCore": step}}}
        )

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence.finished).is_equal_to(
            dict.fromkeys(
                [
                    _in_game(game_dir, DOTNET_PROGRAM),
                    _in_game(game_dir, second_program),
                    game_dir / "DotNetCore" / "hosting-bundle.exe",
                ],
                "DotNetCore",
            )
        )

    @pytest.mark.parametrize("has_registry", [True, False])
    @pytest.mark.parametrize(
        "has_run_key",
        ["HKEY_CURRENT_USER\\" + DOTNET_KEY, DOTNET_KEY, "HKEY_LOCAL_MACHINE", "HKEY_LOCAL_MACHINE\\", {"nested": "x"}],
        ids=["other-hive", "no-hive", "hive-only", "hive-and-separator", "section"],
    )
    def test_has_run_key_that_names_no_local_machine_key_keeps_the_installer(
        self, library: Path, has_run_key: str | VdfDict, has_registry: bool
    ):
        script: VdfDict = {"Run Process": {"DotNetCore": {**DOTNET_STEP, "HasRunKey": has_run_key}}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})
        platform = _recorded((DOTNET_KEY, "DotNetCore"), ("", "DotNetCore"), has_registry=has_registry)

        evidence = collect_installer_evidence(library, platform)

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, DOTNET_PROGRAM)}), finished={})
        )

    def test_hive_name_is_matched_whatever_its_case(self, library: Path):
        script: VdfDict = {
            "Run Process": {"DotNetCore": {**DOTNET_STEP, "HasRunKey": "hkey_Local_Machine\\" + DOTNET_KEY}}
        }
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence.finished).is_equal_to({_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})

    def test_without_a_registry_a_step_with_a_has_run_key_proves_nothing(self, library: Path):
        _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore"), has_registry=False))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    def test_without_a_registry_uninstall_and_unkeyed_steps_still_keep_installers(self, library: Path):
        game_dir = _install_game(library, "Battlefield 6", {"installScript.vdf": ANTICHEAT_SCRIPT})

        evidence = collect_installer_evidence(library, FakePlatformAdapter(has_registry=False))

        assert_that(evidence.needed).is_equal_to(frozenset({_in_game(game_dir, ANTICHEAT_PROGRAM)}))


class TestProgramsAndMentions:
    @pytest.mark.parametrize(
        "program",
        [
            r"%WinDir%\system32\msiexec.exe",
            r"C:\Windows\system32\msiexec.exe",
            r"%INSTALLDIR%\..",
            r"%INSTALLDIR%\redist\..",
            r"%INSTALLDIR%\%LANGUAGE%\setup.exe",
            r"%INSTALLDIR%\C:\Windows\setup.exe",
            r"%INSTALLDIR%backup\setup.exe",
            "%INSTALLDIR%",
            "%INSTALLDIR%\\",
            r"%INSTALLDIR%\.",
            {"nested": r"%INSTALLDIR%\setup.exe"},
        ],
    )
    def test_program_that_is_not_a_file_of_the_game_is_ignored(self, library: Path, program: str | VdfDict):
        script: VdfDict = {"Run Process": {"Setup": {"process 1": program}}}
        _install_game(library, "Odd Game", {"install.vdf": script})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    @pytest.mark.parametrize("field", ["process", "process1", "process 1b", "processNotes", "process one", "command 1"])
    def test_field_not_spelled_as_a_numbered_process_never_makes_a_file_finished(self, library: Path, field: str):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, field: r"%INSTALLDIR%\game.exe"}
        _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    @pytest.mark.parametrize(
        "program",
        [
            r'"%INSTALLDIR%\setup.exe" /silent',
            r"%INSTALLDIR%\setup.exe%TEMP%",
            r'%INSTALLDIR%\setup.exe"x',
            r'"%INSTALLDIR%\setup.exe',
            r'%INSTALLDIR%\setup.exe"',
            r'""%INSTALLDIR%\setup.exe""',
            r'x%INSTALLDIR%\setup.exe"',
            '"',
        ],
        ids=[
            "arguments",
            "variable",
            "stray-quote",
            "opening-quote",
            "closing-quote",
            "doubled-quotes",
            "closing-quote-after-a-stray-character",
            "lone-quote",
        ],
    )
    def test_program_that_is_not_exactly_one_path_is_never_finished(self, library: Path, program: str):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": program}
        _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    @pytest.mark.parametrize(
        ("command", "mentioned"),
        [
            (r'/i "%INSTALLDIR%\redist\vc.msi" /quiet', [r"redist\vc.msi"]),
            (r"/i %installdir%/redist/vc.msi", [r"redist\vc.msi"]),
            (r"/i %INSTALLDIR%\redist\vc.msi /quiet", [r"redist\vc.msi \quiet"]),
            (r'"%INSTALLDIR%\a.msi" "%INSTALLDIR%\b\c.msi"', ["a.msi", r"b\c.msi"]),
            (r"/src=%INSTALLDIR%\data%INSTALLDIR%\more", ["data", "more"]),
            (r'/dir="%INSTALLDIR%" /up="%INSTALLDIR%\..\.." /lang="%INSTALLDIR%\%LANGUAGE%"', []),
            (r'/i "%INSTALLDIR%\bin\..\redist\.\vc.msi"', [r"redist\vc.msi"]),
            (r'/i "%INSTALLDIR%\\redist//vc.msi"', [r"redist\vc.msi"]),
        ],
        ids=[
            "quoted",
            "slashes",
            "unquoted-runs-to-the-end",
            "two",
            "back-to-back",
            "the-game-directory-and-above",
            "dots-collapsed",
            "doubled-separators",
        ],
    )
    def test_step_without_a_record_keeps_every_game_path_its_fields_mention(
        self, library: Path, command: str, mentioned: list[str]
    ):
        step: VdfDict = {"process 1": r"%WinDir%\system32\msiexec.exe", "command 1": command}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(_in_game(game_dir, path) for path in mentioned), finished={})
        )

    def test_unrecorded_step_naming_a_recorded_installer_through_dots_keeps_it(self, library: Path):
        script: VdfDict = {
            "Run Process": {
                "Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM},
                "Repair": {"process 1": r"%INSTALLDIR%\redist\..\redist\setup.exe"},
            }
        }
        game_dir = _install_game(library, "Odd Game", {"install.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, SETUP_PROGRAM)}), finished={})
        )

    @pytest.mark.parametrize("recorded", [True, False], ids=["recorded", "unrecorded"])
    @pytest.mark.parametrize(
        "program",
        [
            r"%INSTALLDIR%\redist\C:\setup.exe",
            r"%INSTALLDIR%\redist\C:setup.exe",
            r"%INSTALLDIR%\redist\D:\setup.exe",
            r"%INSTALLDIR%\redist\setup.exe:stream",
            r"%INSTALLDIR%\C:",
        ],
        ids=["drive-and-root", "drive", "another-drive", "stream", "bare-drive"],
    )
    def test_reference_with_a_colon_names_no_file_of_the_game(self, library: Path, program: str, recorded: bool):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": program, "command 1": f'/x "{program}"'}
        script: VdfDict = {"Run Process": {"Setup": step}}
        _install_game(library, "Odd Game", {"install.vdf": script}, {SETUP_PROGRAM: 100})
        platform = _recorded((SETUP_KEY, "Setup")) if recorded else FakePlatformAdapter()

        evidence = collect_installer_evidence(library, platform)

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    @pytest.mark.parametrize(
        "program",
        [
            r"%INSTALLDIR%\bin\..\redist\setup.exe",
            r"%INSTALLDIR%\\redist\\setup.exe",
            r"%INSTALLDIR%\..\Odd Game\redist\setup.exe",
        ],
        ids=["dots", "doubled-separators", "out-and-back-in"],
    )
    def test_recorded_program_is_finished_under_the_path_windows_reads(self, library: Path, program: str):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": program}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, SETUP_PROGRAM): "Setup"})
        )

    @pytest.mark.parametrize("recorded", [False, True], ids=["unrecorded", "recorded"])
    def test_program_in_another_game_is_kept_while_unrecorded_and_never_finished(self, library: Path, recorded: bool):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\..\Other Game\setup.exe"}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})
        platform = _recorded((SETUP_KEY, "Setup")) if recorded else FakePlatformAdapter()

        evidence = collect_installer_evidence(library, platform)

        other_installer = game_dir.parent / "Other Game" / "setup.exe"
        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset() if recorded else frozenset({other_installer}), finished={})
        )

    def test_directory_whose_name_sorts_below_two_dots_is_a_name_not_a_step_up(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\$Tools\(x86)\-setup.exe"}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={game_dir / "$Tools" / "(x86)" / "-setup.exe": "Setup"})
        )

    def test_program_with_text_around_it_is_kept_under_both_readings(self, library: Path):
        step: VdfDict = {"process 1": "  %INSTALLDIR%\\setup.exe  "}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": {"Run Process": {"Setup": step}}})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence.needed).is_equal_to(frozenset({game_dir / "setup.exe", game_dir / "setup.exe  "}))

    def test_recorded_program_inside_a_directory_another_step_mentions_is_not_finished(self, library: Path):
        script: VdfDict = {
            "Run Process": {
                "Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM},
                "Repair": {"process 1": r"%WinDir%\system32\cmd.exe", "command 1": r'/c dir "%INSTALLDIR%\redist"'},
            }
        }
        game_dir = _install_game(library, "Odd Game", {"install.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset({game_dir / "redist"}), finished={}))

    def test_step_with_its_record_keeps_nothing_its_fields_mention(self, library: Path):
        step: VdfDict = {**DOTNET_STEP, "command 1": r'/log "%INSTALLDIR%\logs\dotnet.log"'}
        game_dir = _install_game(
            library, "Baldurs Gate 3", {"InstallScript.vdf": {"Run Process": {"DotNetCore": step}}}
        )

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})
        )

    @pytest.mark.parametrize(("recorded", "finished"), [(1, False), (2, True)], ids=["below", "at-the-minimum"])
    def test_keys_are_matched_whatever_their_case(self, library: Path, recorded: int, finished: bool):
        game_dir = library / "steamapps" / "common" / "Loud Game"
        game_dir.mkdir(parents=True)
        step: VdfDict = {
            "PROCESS 1": r"%installdir%\setup.exe",
            "HASRUNKEY": HIVE + SETUP_KEY,
            "MINIMUMHASRUNVALUE": "2",
        }
        script: VdfDict = {"INSTALLSCRIPT": {"RUN PROCESS": {"Setup": step}}}
        (game_dir / "install.vdf").write_text(serialize_vdf(script), encoding="utf-8")
        manifest: VdfDict = {"APPSTATE": {"INSTALLDIR": "Loud Game", "INSTALLSCRIPTS": {"1": "install.vdf"}}}
        (library / "steamapps" / "appmanifest_1.acf").write_text(serialize_vdf(manifest), encoding="utf-8")

        platform = FakePlatformAdapter()
        platform.set_registry_dword("HKLM", SETUP_KEY, "Setup", recorded)

        evidence = collect_installer_evidence(library, platform)

        installer = game_dir / "setup.exe"
        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={installer: "Setup"})
            if finished
            else InstallerEvidence(needed=frozenset({installer}), finished={})
        )

    def test_script_in_a_subdirectory_is_found_by_its_windows_path(self, library: Path):
        script_name = r"_CommonRedist\vcredist\2019\installscript.vdf"
        program = r"%INSTALLDIR%\_CommonRedist\vcredist\2019\vc_redist.x64.exe"
        script: VdfDict = {"Run Process": {"x64": {"process 1": program}}}
        game_dir = _install_game(library, "Old Game", {script_name: script})

        assert_that(collect_installer_evidence(library, FakePlatformAdapter()).needed).is_equal_to(
            frozenset({_in_game(game_dir, program)})
        )

    def test_script_with_a_byte_order_mark_and_a_signature_section_is_read(self, library: Path):
        text = "\ufeff" + serialize_vdf({"InstallScript": DOTNET_SCRIPT, "kvsignatures": {"InstallScript": "737f"}})
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": text})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})
        )


class TestRepeatedKeys:
    """Which of two keys that share a name Steam honours was not observed, so neither may hide the other."""

    @pytest.mark.parametrize(
        "script",
        [
            f'"InstallScript" {{ "Run Process" {{ {UNRECORDED_SETUP} }} "RUN PROCESS" {{ {RECORDED_SETUP} }} }}',
            f'"InstallScript" {{ "Run Process" {{ {RECORDED_SETUP} }} "Run Process" {{ {UNRECORDED_SETUP} }} }}',
            f'"InstallScript" {{ "Run Process" {{ {UNRECORDED_SETUP} {RECORDED_SETUP} }} }}',
            f'"InstallScript" {{ "Run Process" {{ {RECORDED_SETUP} {UNRECORDED_SETUP} }} }}',
            f'"InstallScript" {{ "Run Process" {{ {UNRECORDED_SETUP} }} }} '
            f'"installscript" {{ "Run Process" {{ {RECORDED_SETUP} }} }}',
            f'"InstallScript" {{ "Run Process" {{ {RECORDED_SETUP} }} "Run Process On Uninstall" {{ }} '
            f'"RUN PROCESS ON UNINSTALL" {{ {UNRECORDED_SETUP} }} }}',
        ],
        ids=["sections", "sections-reversed", "steps", "steps-reversed", "roots", "uninstall-sections"],
    )
    def test_unrecorded_step_is_not_hidden_by_a_recorded_namesake(self, library: Path, script: str):
        game_dir = _install_game(library, "Twice", {"install.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, SETUP_PROGRAM)}), finished={})
        )

    @pytest.mark.parametrize(
        "repeated_field",
        [
            f'"HasRunKey" "{HIVE}{SETUP_KEY}"',
            f'"hasrunkey" "{HIVE}Software\\Elsewhere"',
            '"MinimumHasRunValue" "1" "MINIMUMHASRUNVALUE" "1"',
        ],
        ids=["same-key-twice", "another-key", "minimum-twice"],
    )
    def test_step_that_repeats_a_record_field_keeps_its_installer(self, library: Path, repeated_field: str):
        fields = f'"HasRunKey" "{HIVE}{SETUP_KEY}" {repeated_field} "process 1" "{SETUP_PROGRAM}"'.replace("\\", "\\\\")
        script = f'"InstallScript" {{ "Run Process" {{ "Setup" {{ {fields} }} }} }}'
        game_dir = _install_game(library, "Twice", {"install.vdf": script})

        evidence = collect_installer_evidence(
            library, _recorded((SETUP_KEY, "Setup"), (r"Software\Elsewhere", "Setup"))
        )

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, SETUP_PROGRAM)}), finished={})
        )

    def test_both_programs_of_a_repeated_process_field_are_sorted(self, library: Path):
        fields = f'"HasRunKey" "{HIVE}{SETUP_KEY}" "process 1" "%INSTALLDIR%\\a.exe" "process 1" "%INSTALLDIR%\\b.exe"'
        script = f'"InstallScript" {{ "Run Process" {{ "Setup" {{ {fields} }} }} }}'.replace("\\", "\\\\")
        game_dir = _install_game(library, "Twice", {"install.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence.finished).is_equal_to({game_dir / "a.exe": "Setup", game_dir / "b.exe": "Setup"})

    def test_keys_repeated_outside_the_process_sections_do_not_matter(self, library: Path):
        firewall = '"Firewall" { "AoE II" "%INSTALLDIR%\\\\AoE2DE_s.exe" "AoE II" "%INSTALLDIR%\\\\Battle.exe" }'
        script = f'"InstallScript" {{ {firewall} "Run Process" {{ {RECORDED_SETUP} }} }}'
        game_dir = _install_game(library, "AoE2DE", {"813780_install.vdf": script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, SETUP_PROGRAM): "Setup"})
        )


class TestLinkedPrograms:
    def _game_with_linked_tools(self, library: Path, script: VdfDict, link_target: Path | None = None) -> Path:
        game_dir = _install_game(library, "Linked", {"install.vdf": script}, {SETUP_PROGRAM: 100})
        (game_dir / "tools").symlink_to(link_target or game_dir / "redist", target_is_directory=True)
        return game_dir

    def test_program_named_through_a_link_is_kept_under_both_names(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\tools\setup.exe"}
        game_dir = self._game_with_linked_tools(library, {"Run Process": {"Setup": step}})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(
                needed=frozenset({game_dir / "tools" / "setup.exe", game_dir / "redist" / "setup.exe"}), finished={}
            )
        )

    def test_uninstall_step_through_a_link_keeps_the_file_a_recorded_step_names_directly(self, library: Path):
        script: VdfDict = {
            "Run Process": {"Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM}},
            "Run Process On Uninstall": {"Remove": {"process 1": r"%INSTALLDIR%\tools\setup.exe"}},
        }
        game_dir = self._game_with_linked_tools(library, script)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence.finished).is_empty()
        assert_that(evidence.protects(game_dir / "redist")).is_true()
        assert_that(evidence.protects(game_dir / "redist" / "setup.exe")).is_true()

    def test_program_whose_link_leaves_the_game_is_kept_by_its_name(self, library: Path, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "setup.exe").write_bytes(b"\x00" * 100)
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\tools\setup.exe"}
        game_dir = self._game_with_linked_tools(library, {"Run Process": {"Setup": step}}, outside)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({game_dir / "tools" / "setup.exe"}), finished={})
        )

    def test_padded_program_named_through_a_link_is_kept_under_every_reading(self, library: Path):
        step: VdfDict = {"process 1": "%INSTALLDIR%\\tools\\setup.exe  "}
        game_dir = self._game_with_linked_tools(library, {"Run Process": {"Setup": step}})

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence.needed).is_equal_to(
            frozenset(
                {
                    game_dir / "tools" / "setup.exe",
                    game_dir / "tools" / "setup.exe  ",
                    game_dir / "redist" / "setup.exe",
                }
            )
        )

    def test_program_behind_a_link_that_points_at_itself_is_kept(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\tools\setup.exe"}
        game_dir = _install_game(library, "Linked", {"install.vdf": {"Run Process": {"Setup": step}}})
        (game_dir / "tools").symlink_to("tools", target_is_directory=True)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({game_dir / "tools" / "setup.exe"}), finished={})
        )

    def test_program_that_is_itself_a_link_is_kept_under_both_names(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\launch.exe"}
        script: VdfDict = {"Run Process": {"Setup": step}}
        game_dir = _install_game(library, "Linked", {"install.vdf": script}, {SETUP_PROGRAM: 100})
        (game_dir / "launch.exe").symlink_to(game_dir / "redist" / "setup.exe")

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(
                needed=frozenset({game_dir / "launch.exe", game_dir / "redist" / "setup.exe"}), finished={}
            )
        )

    @pytest.mark.skipif(
        sys.platform != "win32", reason="only Windows opens a name with a trailing dot as the bare name"
    )
    def test_program_named_with_a_trailing_dot_is_kept_under_both_names(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM + "."}
        script: VdfDict = {"Run Process": {"Setup": step}}
        game_dir = _install_game(library, "Dotted", {"install.vdf": script}, {SETUP_PROGRAM: 100})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(
                needed=frozenset({game_dir / "redist" / "setup.exe.", game_dir / "redist" / "setup.exe"}), finished={}
            )
        )

    def test_program_that_is_a_link_pointing_at_itself_is_kept(self, library: Path):
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\launch.exe"}
        game_dir = _install_game(library, "Linked", {"install.vdf": {"Run Process": {"Setup": step}}})
        (game_dir / "launch.exe").symlink_to("launch.exe")

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset({game_dir / "launch.exe"}), finished={}))

    @pytest.mark.parametrize("link_target", [".", "..", "../.."], ids=["the-game", "its-parent", "its-grandparent"])
    def test_program_that_is_a_link_to_the_game_directory_or_above_keeps_the_whole_game(
        self, library: Path, link_target: str
    ):
        script: VdfDict = {
            "Run Process": {
                "Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM},
                "Open": {"process 1": r"%INSTALLDIR%\root"},
            }
        }
        game_dir = _install_game(library, "Linked", {"install.vdf": script}, {SETUP_PROGRAM: 100})
        (game_dir / "root").symlink_to(link_target, target_is_directory=True)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({game_dir / "root", game_dir}), finished={})
        )

    @pytest.mark.parametrize("denied_name", ["locked", "launch.exe"], ids=["its-directory", "the-program"])
    def test_program_on_a_path_that_cannot_be_inspected_is_kept(self, library: Path, monkeypatch, denied_name: str):
        program = r"%INSTALLDIR%\locked\launch.exe"
        script: VdfDict = {"Run Process": {"Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": program}}}
        game_dir = _install_game(library, "Locked", {"install.vdf": script}, {program: 100})
        lstat = Path.lstat

        def deny_inspection(path: Path):
            if path.name == denied_name:
                raise PermissionError(13, "Access is denied", str(path))
            return lstat(path)

        monkeypatch.setattr(Path, "lstat", deny_inspection)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, program)}), finished={})
        )

    @pytest.mark.skipif(sys.platform != "win32", reason="junctions are an NTFS reparse point")
    @pytest.mark.parametrize("inspections_allowed", [1, None], ids=["only-the-first-inspection-works", "plain"])
    def test_program_behind_a_junction_is_kept(
        self, library: Path, tmp_path: Path, monkeypatch, inspections_allowed: int | None
    ):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "setup.exe").write_bytes(b"\x00" * 100)
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\tools\setup.exe"}
        game_dir = _install_game(library, "Linked", {"install.vdf": {"Run Process": {"Setup": step}}})
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(game_dir / "tools"), str(outside)], check=True, capture_output=True
        )
        lstat = Path.lstat
        inspections: list[Path] = []

        def allow_first_inspections(path: Path):
            if path.name == "tools":
                inspections.append(path)
                if inspections_allowed is not None and len(inspections) > inspections_allowed:
                    raise PermissionError(13, "Access is denied", str(path))
            return lstat(path)

        monkeypatch.setattr(Path, "lstat", allow_first_inspections)

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({game_dir / "tools" / "setup.exe"}), finished={})
        )

    def test_library_reached_through_a_link_changes_nothing(self, library: Path, tmp_path: Path):
        _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT}, {DOTNET_PROGRAM: 100})
        linked_library = tmp_path / "LinkedSteam"
        linked_library.symlink_to(library, target_is_directory=True)

        evidence = collect_installer_evidence(linked_library, _recorded((DOTNET_KEY, "DotNetCore")))

        linked_game = linked_library / "steamapps" / "common" / "Baldurs Gate 3"
        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(linked_game, DOTNET_PROGRAM): "DotNetCore"})
        )


class TestUnreadableScripts:
    @pytest.mark.parametrize(
        "broken_script",
        [
            '"InstallScript" { "Run Process" { "Remove" { "process 1" "%INSTALLDIR%\\\\redist\\\\setup.exe" }',
            '"Firewall" { "Game" "%INSTALLDIR%\\\\game.exe" }',
            '"InstallScript" "not a section"',
            "\x00",
            "",
            "  \n// only a comment\n",
        ],
        ids=[
            "unterminated",
            "no-install-script-section",
            "install-script-is-a-value",
            "one-odd-token",
            "empty",
            "only-a-comment",
        ],
    )
    def test_game_with_a_script_that_cannot_be_read_is_kept_whole(self, library: Path, broken_script: str):
        recorded_script: VdfDict = {
            "Run Process": {"Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": SETUP_PROGRAM}}
        }
        game_dir = _install_game(library, "Broken", {"install.vdf": recorded_script, "uninstall.vdf": broken_script})

        evidence = collect_installer_evidence(library, _recorded((SETUP_KEY, "Setup")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={}, kept_whole=frozenset({game_dir}))
        )

    def test_script_that_is_not_utf_8_is_unreadable(self, library: Path):
        game_dir = _install_game(library, "Broken", {"install.vdf": DOTNET_SCRIPT})
        script_bytes = serialize_vdf({"InstallScript": DOTNET_SCRIPT}).encode("utf-8")
        (game_dir / "install.vdf").write_bytes(script_bytes.replace(b"DotNetCore", b"DotNet\xe9Core"))

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={}, kept_whole=frozenset({game_dir}))
        )

    def test_script_that_cannot_be_opened_is_unreadable(self, library: Path):
        game_dir = _install_game(library, "Broken", {})
        (game_dir / "install.vdf").mkdir()
        _write_manifest(library, 1, {"installdir": "Broken", "InstallScripts": {"1": "install.vdf"}})

        assert_that(collect_installer_evidence(library, FakePlatformAdapter()).kept_whole).is_equal_to(
            frozenset({game_dir})
        )

    @pytest.mark.parametrize(
        "script_name",
        [r"..\Other Game\install.vdf", r"C:\install.vdf", "", {"nested": "install.vdf"}],
        ids=["parent", "anchored", "empty", "section"],
    )
    def test_script_listed_under_a_name_outside_the_game_is_unreadable(self, library: Path, script_name: str | VdfDict):
        game_dir = _install_game(library, "Broken", {})
        _write_manifest(library, 1, {"installdir": "Broken", "InstallScripts": {"1": script_name}})

        assert_that(collect_installer_evidence(library, FakePlatformAdapter()).kept_whole).is_equal_to(
            frozenset({game_dir})
        )

    def test_listed_script_that_is_absent_leaves_the_game_to_the_other_scripts(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"install.vdf": DOTNET_SCRIPT, "other.vdf": ""})
        (game_dir / "other.vdf").unlink()

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})
        )

    def test_unreadable_script_does_not_hide_what_the_readable_ones_need(self, library: Path):
        scripts: dict[str, VdfDict | str] = {"broken.vdf": "{", "install.vdf": {"Run Process": ANTICHEAT_RUN_STEPS}}
        game_dir = _install_game(library, "Battlefield 6", scripts)

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(
            InstallerEvidence(
                needed=frozenset({_in_game(game_dir, ANTICHEAT_PROGRAM)}), finished={}, kept_whole=frozenset({game_dir})
            )
        )

    def test_unreadable_script_of_one_game_leaves_the_others_alone(self, library: Path):
        broken_game = _install_game(library, "Broken", {"install.vdf": "{"})
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(
                needed=frozenset(),
                finished={_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"},
                kept_whole=frozenset({broken_game}),
            )
        )


class TestUnreadableManifests:
    @pytest.mark.parametrize(
        "manifest_text",
        [
            '"AppState" { "installdir" "Orphan"',
            '"AppState" { "appid" "9" }',
            '"AppState" "not a section"',
            '"AppState" { "installdir" "Orphan" "installdir" "Baldurs Gate 3" }',
            '"AppState" { "installdir" "Orphan" } "AppState" { "installdir" "Baldurs Gate 3" }',
            '"AppState" { "installdir" { "nested" "Orphan" } }',
            '"AppState" { "installdir" ".." }',
            '"AppState" { "installdir" "." }',
            '"AppState" { "installdir" "Orphan\\\\bin" }',
            '"AppState" { "installdir" "C:" }',
            "",
            '"AppState" { "installdir" "" }',
            '"AppState" { "installdir" "Baldurs Gate 3\\\\." }',
            '"AppState" { "installdir" ".\\\\Baldurs Gate 3" }',
            '"AppState" { "installdir" "Baldurs Gate 3\\\\" }',
            '"AppState" { "installdir" "Baldurs Gate 3/" }',
            '"AppState" { "installdir" "Baldurs Gate 3." }',
            '"AppState" { "installdir" "Baldurs Gate 3 " }',
        ],
        ids=[
            "unterminated",
            "no-installdir",
            "appstate-is-a-value",
            "two-installdirs",
            "two-appstates",
            "installdir-is-a-section",
            "parent",
            "current",
            "nested-directory",
            "drive",
            "empty",
            "empty-installdir",
            "described-game-then-dot",
            "dot-then-described-game",
            "described-game-then-backslash",
            "described-game-then-slash",
            "described-game-with-trailing-dot",
            "described-game-with-trailing-space",
        ],
    )
    def test_manifest_that_names_no_one_game_stops_the_library_calling_anything_finished(
        self, library: Path, manifest_text: str
    ):
        described = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})
        unreadable_game = _install_game(library, "Broken", {"install.vdf": "{"})
        orphan = library / "steamapps" / "common" / "Orphan"
        orphan.mkdir()
        (library / "steamapps" / "appmanifest_9.acf").write_text(manifest_text, encoding="utf-8")

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={}, kept_whole=frozenset({orphan, unreadable_game}))
        )
        assert_that(evidence.protects(described / "redist")).is_false()

    def test_manifest_that_cannot_be_opened_counts_as_unreadable(self, library: Path):
        _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})
        (library / "steamapps" / "appmanifest_9.acf").mkdir()

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence).is_equal_to(InstallerEvidence(needed=frozenset(), finished={}))

    @pytest.mark.parametrize("unreadable_id", ["1", "9"], ids=["read-before-it", "read-after-it"])
    def test_what_a_readable_manifest_needs_is_still_kept(self, library: Path, unreadable_id: str):
        game_dir = _install_game(library, "Battlefield 6", {"installScript.vdf": ANTICHEAT_SCRIPT})
        (library / "steamapps" / f"appmanifest_{unreadable_id}.acf").write_text("{", encoding="utf-8")

        evidence = collect_installer_evidence(library, FakePlatformAdapter())

        assert_that(evidence).is_equal_to(
            InstallerEvidence(needed=frozenset({_in_game(game_dir, ANTICHEAT_PROGRAM)}), finished={})
        )

    def test_same_install_directory_stated_twice_names_one_game(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})
        manifest = (
            '"AppState" { "installdir" "Baldurs Gate 3" "INSTALLDIR" "Baldurs Gate 3" '
            '"InstallScripts" { "1" "InstallScript.vdf" } }'
        )
        (library / "steamapps" / "appmanifest_14.acf").write_text(manifest, encoding="utf-8")

        evidence = collect_installer_evidence(library, _recorded((DOTNET_KEY, "DotNetCore")))

        assert_that(evidence.finished).is_equal_to({_in_game(game_dir, DOTNET_PROGRAM): "DotNetCore"})

    def test_library_without_manifests_has_no_evidence(self, library: Path):
        (library / "steamapps" / "common" / "Orphan").mkdir()

        assert_that(collect_installer_evidence(library, FakePlatformAdapter())).is_equal_to(
            InstallerEvidence(needed=frozenset(), finished={})
        )


class TestReadGameScripts:
    def test_step_is_read_with_its_programs_what_it_reaches_and_its_record(self, library: Path):
        step: VdfDict = {**DOTNET_STEP, "command 1": r'/log "%INSTALLDIR%\logs"', "MinimumHasRunValue": "3"}
        game_dir = _install_game(
            library, "Baldurs Gate 3", {"InstallScript.vdf": {"Run Process": {"DotNetCore": step}}}
        )
        manifest_path = library / "steamapps" / "appmanifest_14.acf"

        installer = _in_game(game_dir, DOTNET_PROGRAM)
        assert_that(read_game_scripts(manifest_path, library)).is_equal_to(
            GameScripts(
                install_dir=game_dir,
                steps=(
                    InstallStep(
                        name="DotNetCore",
                        programs=(installer,),
                        reached=(installer, game_dir / "logs"),
                        completion_subkey=DOTNET_KEY,
                        completion_minimum=3,
                    ),
                ),
                unreadable=False,
            )
        )

    def test_uninstall_step_has_no_record_that_settles_it(self, library: Path):
        script: VdfDict = {"Run Process On Uninstall": {"DotNetCore": DOTNET_STEP}}
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": script})
        manifest_path = library / "steamapps" / "appmanifest_14.acf"

        installer = _in_game(game_dir, DOTNET_PROGRAM)
        assert_that(read_game_scripts(manifest_path, library)).is_equal_to(
            GameScripts(
                install_dir=game_dir,
                steps=(
                    InstallStep(
                        name="DotNetCore",
                        programs=(installer,),
                        reached=(installer,),
                        completion_subkey=None,
                        completion_minimum=1,
                    ),
                ),
                unreadable=False,
            )
        )

    @pytest.mark.parametrize(
        "script",
        [
            pytest.param({"Run Process": "scalar"}, id="section-is-a-value"),
            pytest.param({"Run Process": {"Setup": "scalar"}}, id="step-is-a-value"),
            pytest.param({"Firewall": {"Game": r"%INSTALLDIR%\game.exe"}}, id="other-section"),
            pytest.param({}, id="empty"),
        ],
    )
    def test_script_without_process_steps_yields_no_steps(self, library: Path, script: VdfDict):
        game_dir = _install_game(library, "Game", {"install.vdf": script})
        manifest_path = library / "steamapps" / "appmanifest_4.acf"

        assert_that(read_game_scripts(manifest_path, library)).is_equal_to(
            GameScripts(install_dir=game_dir, steps=(), unreadable=False)
        )

    def test_manifest_without_install_scripts_describes_a_game_with_no_steps(self, library: Path):
        manifest_path = _write_manifest(library, 3, {"installdir": "Quiet Game"})

        assert_that(read_game_scripts(manifest_path, library)).is_equal_to(
            GameScripts(install_dir=library / "steamapps" / "common" / "Quiet Game", steps=(), unreadable=False)
        )

    def test_absent_manifest_describes_no_game(self, library: Path):
        assert_that(read_game_scripts(library / "steamapps" / "appmanifest_404.acf", library)).is_none()


class TestEvidenceProtects:
    def test_protects_what_is_needed_what_holds_it_and_what_lies_inside_it(self, tmp_path: Path):
        installer = tmp_path / "Game" / "_CommonRedist" / "vcredist" / "vc_redist.x64.exe"
        payload_dir = tmp_path / "Game" / "payload"
        evidence = InstallerEvidence(needed=frozenset({installer, payload_dir}), finished={})

        assert_that(evidence.protects(installer)).is_true()
        assert_that(evidence.protects(installer.parent)).is_true()
        assert_that(evidence.protects(tmp_path / "Game" / "_CommonRedist")).is_true()
        assert_that(evidence.protects(payload_dir / "data" / "crash.dmp")).is_true()

    def test_protects_a_game_kept_whole_and_everything_in_it(self, tmp_path: Path):
        evidence = InstallerEvidence(needed=frozenset(), finished={}, kept_whole=frozenset({tmp_path / "Game"}))

        assert_that(evidence.protects(tmp_path / "Game")).is_true()
        assert_that(evidence.protects(tmp_path / "Game" / "redist")).is_true()
        assert_that(evidence.protects(tmp_path / "Game" / "bin" / "crash.dmp")).is_true()
        assert_that(evidence.protects(tmp_path / "Other Game" / "redist")).is_false()

    def test_does_not_protect_other_paths(self, tmp_path: Path):
        installer = tmp_path / "Game" / "_CommonRedist" / "vcredist" / "vc_redist.x64.exe"
        evidence = InstallerEvidence(needed=frozenset({installer}), finished={})

        assert_that(evidence.protects(tmp_path / "Game" / "_CommonRedist" / "DirectX")).is_false()
        assert_that(evidence.protects(installer.with_name("vc_redist.x86.exe"))).is_false()
        assert_that(evidence.protects(tmp_path / "Game" / "crash.dmp")).is_false()


class TestSteamClientInstallers:
    def _client(self, library: Path, platform: FakePlatformAdapter | None = None) -> SteamClient:
        platform = platform or FakePlatformAdapter()
        platform.set_registry("HKLM", r"SOFTWARE\Wow6432Node\Valve\Steam", "InstallPath", str(library))
        return SteamClient(platform, ExclusionRegistry())

    def test_installer_whose_step_has_its_record_is_offered_with_the_evidence(self, library: Path):
        game_dir = _install_game(
            library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT}, {DOTNET_PROGRAM: 5000}
        )

        entries = list(self._client(library, _recorded((DOTNET_KEY, "DotNetCore"))).scan_safe())

        assert_that(
            [(entry.path, entry.category, entry.size_bytes, entry.description, entry.game_root) for entry in entries]
        ).is_equal_to(
            [
                (
                    _in_game(game_dir, DOTNET_PROGRAM),
                    JunkCategory.INSTALLER,
                    5000,
                    "Installer in Baldurs Gate 3, Steam install step recorded as complete (DotNetCore)",
                    game_dir,
                )
            ]
        )

    def test_installer_whose_step_has_no_record_is_not_offered_as_finished(self, library: Path):
        _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT}, {DOTNET_PROGRAM: 5000})

        assert_that(list(self._client(library).scan_safe())).is_empty()

    @pytest.mark.parametrize("link_target", [".", ".."], ids=["the-game-directory", "above-the-game-directory"])
    def test_step_whose_program_is_a_link_to_the_game_directory_keeps_the_whole_game(
        self, library: Path, link_target: str
    ):
        script: VdfDict = {
            "Run Process": {
                "Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\_CommonRedist\setup.exe"},
                "Open": {"process 1": r"%INSTALLDIR%\root"},
            }
        }
        files = {r"%INSTALLDIR%\_CommonRedist\setup.exe": 4000, r"%INSTALLDIR%\crash.dmp": 900}
        game_dir = _install_game(library, "Linked", {"install.vdf": script}, files)
        (game_dir / "root").symlink_to(link_target, target_is_directory=True)

        entries = list(self._client(library, _recorded((SETUP_KEY, "Setup"))).scan_safe())

        assert_that(entries).is_empty()

    def test_redist_directory_holding_a_needed_installer_is_kept(self, library: Path, caplog):
        program = r"%INSTALLDIR%\_CommonRedist\vcredist\2019\vc_redist.x64.exe"
        key = r"Software\Valve\Steam\Apps\CommonRedist\vcredist\2019"
        script: VdfDict = {"Run Process": {"x64 14.28": {"HasRunKey": HIVE + key, "process 1": program}}}
        files = {program: 4000, r"%INSTALLDIR%\OtherRedist\dxsetup.exe": 700}
        game_dir = _install_game(library, "Old Game", {"installscript.vdf": script}, files)

        with caplog.at_level("INFO", logger="steamcleaner.clients.steam"):
            entries = list(self._client(library).scan_safe())

        assert_that([entry.path for entry in entries]).is_equal_to([game_dir / "OtherRedist"])
        assert_that(caplog.messages).is_equal_to(
            [f"Kept, an install script of Steam may still need it: {game_dir / '_CommonRedist'}"]
        )

    def test_entry_found_after_a_kept_one_is_still_offered(self, library: Path):
        program = r"%INSTALLDIR%\_CommonRedist\vc_redist.x64.exe"
        script: VdfDict = {"Run Process": {"x64": {"process 1": program}}}
        files = {program: 4000, r"%INSTALLDIR%\OtherRedist\dxsetup.exe": 700}
        game_dir = _install_game(library, "Old Game", {"installscript.vdf": script}, files)
        found_in_this_order = [
            JunkEntry(
                path=game_dir / directory_name,
                category=JunkCategory.REDISTRIBUTABLE,
                size_bytes=1,
                client_name="Steam",
                game_root=game_dir,
            )
            for directory_name in ("_CommonRedist", "OtherRedist")
        ]

        with patch("steamcleaner.clients.steam.scan_game", return_value=iter(found_in_this_order)):
            entries = list(self._client(library).scan_safe())

        assert_that([(entry.path, entry.size_bytes) for entry in entries]).is_equal_to(
            [(game_dir / "OtherRedist", 700)]
        )

    def test_recorded_installer_inside_a_directory_another_step_needs_is_not_offered(self, library: Path):
        script: VdfDict = {
            "Run Process": {
                "Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": r"%INSTALLDIR%\payload\setup.exe"},
                "Repair": {"process 1": r"%WinDir%\system32\cmd.exe", "command 1": r'/c dir "%INSTALLDIR%\payload"'},
            }
        }
        files = {r"%INSTALLDIR%\payload\setup.exe": 4000, r"%INSTALLDIR%\OtherRedist\dxsetup.exe": 700}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": script}, files)

        entries = list(self._client(library, _recorded((SETUP_KEY, "Setup"))).scan_safe())

        assert_that([entry.path for entry in entries]).is_equal_to([game_dir / "OtherRedist"])

    def test_without_a_registry_a_keyed_installer_is_judged_by_directory_name_alone(self, library: Path):
        program = r"%INSTALLDIR%\_CommonRedist\vcredist\2019\vc_redist.x64.exe"
        script: VdfDict = {"Run Process": {"x64 14.28": {"HasRunKey": HIVE + SETUP_KEY, "process 1": program}}}
        files = {program: 4000, r"%INSTALLDIR%\DotNetCore\runtime.exe": 700}
        game_dir = _install_game(library, "Old Game", {"installscript.vdf": script}, files)

        entries = list(self._client(library, FakePlatformAdapter(has_registry=False)).scan_safe())

        assert_that([(entry.path, entry.category) for entry in entries]).is_equal_to(
            [(game_dir / "_CommonRedist", JunkCategory.REDISTRIBUTABLE)]
        )

    def test_redist_directory_whose_installer_has_its_record_is_offered_once(self, library: Path):
        program = r"%INSTALLDIR%\_CommonRedist\vcredist\2019\vc_redist.x64.exe"
        key = r"Software\Valve\Steam\Apps\CommonRedist\vcredist\2019"
        script: VdfDict = {"Run Process": {"x64 14.28": {"HasRunKey": HIVE + key, "process 1": program}}}
        game_dir = _install_game(library, "Old Game", {"installscript.vdf": script}, {program: 4000})

        entries = list(self._client(library, _recorded((key, "x64 14.28"))).scan_safe())

        assert_that([(entry.path, entry.category) for entry in entries]).is_equal_to(
            [(game_dir / "_CommonRedist", JunkCategory.REDISTRIBUTABLE)]
        )

    def test_finished_installer_already_found_as_a_file_is_offered_once(self, library: Path):
        program = r"%INSTALLDIR%\tools\setup.dmp"
        script: VdfDict = {"Run Process": {"Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": program}}}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": script}, {program: 4000})

        entries = list(self._client(library, _recorded((SETUP_KEY, "Setup"))).scan_safe())

        assert_that([(entry.path, entry.category) for entry in entries]).is_equal_to(
            [(_in_game(game_dir, program), JunkCategory.CRASH_DUMP)]
        )

    def test_game_with_an_unreadable_script_offers_nothing(self, library: Path, caplog):
        files = {r"%INSTALLDIR%\_CommonRedist\vc_redist.x64.exe": 4000, r"%INSTALLDIR%\crash.dmp": 900}
        game_dir = _install_game(library, "Broken", {"install.vdf": "{"}, files)

        with caplog.at_level("INFO", logger="steamcleaner.clients.steam"):
            entries = list(self._client(library).scan_safe())

        assert_that(entries).is_empty()
        assert_that(sorted(caplog.messages)).is_equal_to(
            sorted(
                f"Kept, an install script of Steam may still need it: {kept}"
                for kept in (game_dir / "_CommonRedist", game_dir / "crash.dmp")
            )
        )

    def test_finished_installer_that_is_gone_is_not_offered(self, library: Path):
        _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})

        assert_that(list(self._client(library, _recorded((DOTNET_KEY, "DotNetCore"))).scan_safe())).is_empty()

    def test_finished_installer_that_is_a_directory_is_not_offered(self, library: Path):
        game_dir = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT})
        directory_named_like_the_installer = _in_game(game_dir, DOTNET_PROGRAM)
        directory_named_like_the_installer.mkdir(parents=True)
        (directory_named_like_the_installer / "payload.bin").write_bytes(b"\x00" * 5000)

        assert_that(list(self._client(library, _recorded((DOTNET_KEY, "DotNetCore"))).scan_safe())).is_empty()

    @pytest.mark.parametrize("first_program_is", ["gone", "a directory"])
    def test_installer_after_one_that_cannot_be_offered_is_still_offered(self, library: Path, first_program_is: str):
        first_program = r"%INSTALLDIR%\tools\first.exe"
        second_program = r"%INSTALLDIR%\tools\second.exe"
        step: VdfDict = {"HasRunKey": HIVE + SETUP_KEY, "process 1": first_program, "process 2": second_program}
        script: VdfDict = {"Run Process": {"Setup": step}}
        game_dir = _install_game(library, "Odd Game", {"install.vdf": script}, {second_program: 4000})
        if first_program_is == "a directory":
            _in_game(game_dir, first_program).mkdir()
            (_in_game(game_dir, first_program) / "payload.bin").write_bytes(b"\x00" * 5000)

        entries = list(self._client(library, _recorded((SETUP_KEY, "Setup"))).scan_safe())

        assert_that([(entry.path, entry.category) for entry in entries]).is_equal_to(
            [(_in_game(game_dir, second_program), JunkCategory.INSTALLER)]
        )

    def test_finished_installers_of_two_games_are_each_offered_under_their_own_game(self, library: Path):
        tool = r"%INSTALLDIR%\tools\setup.exe"
        tool_script: VdfDict = {"Run Process": {"Setup": {"HasRunKey": HIVE + SETUP_KEY, "process 1": tool}}}
        read_first = _install_game(library, "Alpha", {"InstallScript.vdf": DOTNET_SCRIPT}, {DOTNET_PROGRAM: 5000})
        read_second = _install_game(library, "Beta Game", {"install.vdf": tool_script}, {tool: 4000})
        platform = _recorded((DOTNET_KEY, "DotNetCore"), (SETUP_KEY, "Setup"))

        entries = list(self._client(library, platform).scan_safe())

        assert_that({(entry.path, entry.game_root) for entry in entries}).is_equal_to(
            {(_in_game(read_first, DOTNET_PROGRAM), read_first), (_in_game(read_second, tool), read_second)}
        )

    def test_finished_installer_of_another_game_is_listed_under_its_own_game(self, library: Path):
        first = _install_game(library, "Baldurs Gate 3", {"InstallScript.vdf": DOTNET_SCRIPT}, {DOTNET_PROGRAM: 5000})
        _install_game(library, "Quiet Game", {})

        entries = list(self._client(library, _recorded((DOTNET_KEY, "DotNetCore"))).scan_safe())

        assert_that([(entry.path, entry.game_root) for entry in entries]).is_equal_to(
            [(_in_game(first, DOTNET_PROGRAM), first)]
        )

    def test_finished_installer_under_an_excluded_path_is_not_offered(self, library: Path):
        program = r"%INSTALLDIR%\Tools\DXSETUP.exe"
        key = r"Software\Valve\Steam\Apps\CommonRedist\DirectX\Jun2010"
        script: VdfDict = {"Run Process": {"dxsetup": {"HasRunKey": HIVE + key, "process 1": program}}}
        _install_game(library, "Steamworks Shared", {"installscript.vdf": script}, {program: 4000})

        assert_that(list(self._client(library, _recorded((key, "dxsetup"))).scan_safe())).is_empty()
