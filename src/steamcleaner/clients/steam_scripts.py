"""What Steam's own install scripts say about the installers a game ships.

A game's app manifest lists its install scripts. A script names the programs Steam starts when the game is
first launched ("Run Process") and when it is uninstalled ("Run Process On Uninstall"). For a first-launch
step it may name a registry key, `HasRunKey`, under which Steam keeps a completion record: a DWORD named
after the step, in the 32-bit view of HKEY_LOCAL_MACHINE.

This module reads that as evidence in both directions. A program whose every step has its completion
record is taken as done with, on the assumption that Steam does not start a recorded step again. Whatever
a step without such a record refers to must stay: its programs, where they really are behind a symlink or
junction, and every other `%INSTALLDIR%` path in its fields. A record settles nothing for an uninstall
step, for a step without exactly one `HasRunKey` under HKEY_LOCAL_MACHINE, for one whose
`MinimumHasRunValue` is not a plain number, and for one that reaches a program through a link or through a
path that cannot be inspected.

On a platform without a registry no record can be read. A step a record could settle then neither keeps
nor releases anything, and what it names is judged by directory name alone, as it was before this module.

A game is kept whole when a script its manifest lists exists but cannot be read as an install script. When
an app manifest does not name one game, nothing in that library is called finished and every game
directory no readable manifest describes is kept whole.

The record belongs to a key and a step name, not to a file: two games that share both share the record.
"""

import logging
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Final

from steamcleaner.utils.fs import is_reparse_stat, list_subdirs
from steamcleaner.utils.vdf import parse_vdf_pairs

if TYPE_CHECKING:
    from collections.abc import Iterator

    from steamcleaner.platform.base import PlatformAdapter
    from steamcleaner.utils.vdf import VdfPairs

_logger = logging.getLogger(__name__)

_INSTALL_DIR_REFERENCE: Final = re.compile(r'%installdir%[\\/]([^"%]*)', re.IGNORECASE)
_PROCESS_KEY: Final = re.compile(r"process [0-9]+")
_DWORD: Final = re.compile(r"[0-9]{1,10}")
_RUN_SECTION: Final = "run process"
_UNINSTALL_SECTION: Final = "run process on uninstall"
_LOCAL_MACHINE_HIVE: Final = "hkey_local_machine"


@dataclass(frozen=True, slots=True, kw_only=True)
class InstallStep:
    """One step of an install script.

    programs: the game files its `process N` fields start. reached: the programs, where they really are
    behind a symlink or junction, and every `%INSTALLDIR%` path its fields mention, inside the game or not.
    A mention of the game directory itself, or of a directory that holds it, is left out. completion_subkey:
    the key under HKEY_LOCAL_MACHINE that holds its completion record, or None when no record can settle
    the step. completion_minimum: the least value that record must hold.
    """

    name: str
    programs: tuple[Path, ...]
    reached: tuple[Path, ...]
    completion_subkey: str | None
    completion_minimum: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GameScripts:
    """The install steps of one game. unreadable: a script the manifest lists cannot be read as one."""

    install_dir: Path
    steps: tuple[InstallStep, ...]
    unreadable: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InstallerEvidence:
    """What the install scripts of a library establish.

    needed: paths referred to by a step that no record can settle or, where a registry can be read, whose
    record is absent, is not a DWORD or is below the step's minimum. finished: programs whose every step has
    a record that reaches its minimum and that nothing needed or kept whole covers, each with the name of
    such a step. kept_whole: game directories with a script that cannot be read and, when a manifest names
    no one game, every game directory no readable manifest describes.
    """

    needed: frozenset[Path]
    finished: dict[Path, str]
    kept_whole: frozenset[Path] = frozenset()

    def protects(self, path: Path) -> bool:
        """Whether path is, holds or lies inside something an install script may still need."""
        return any(
            kept == path or kept in path.parents or path in kept.parents for kept in (*self.needed, *self.kept_whole)
        )


def _parse_file(path: Path) -> VdfPairs:
    return parse_vdf_pairs(path.read_text(encoding="utf-8-sig"))


def _sections(pairs: VdfPairs, name: str) -> Iterator[VdfPairs]:
    for key, value in pairs:
        if key.lower() == name and not isinstance(value, str):
            yield value


def _values(pairs: VdfPairs, name: str) -> list[str | VdfPairs]:
    return [value for key, value in pairs if key.lower() == name]


def _follow(relative_text: str, directory: Path) -> Path | None:
    """Follow a Windows relative path from directory, `..` stepping up as Windows reads it.

    None when it has a colon anywhere: that names a drive or a stream, and pathlib would join it as one.
    """
    if ":" in relative_text:
        return None
    target = directory
    for part in PureWindowsPath(relative_text.lstrip("\\/")).parts:
        target = target.parent if part == ".." else target / part
    return target


def _resolve_inside(relative_text: str, directory: Path) -> Path | None:
    target = _follow(relative_text, directory)
    return target if target is not None and directory in target.parents else None


def _resolve_program(value: str, install_dir: Path) -> Path | None:
    """Resolve a value that is exactly `%INSTALLDIR%\\<path>`, bare or in one pair of quotes, inside the game."""
    text = value.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    reference = _INSTALL_DIR_REFERENCE.fullmatch(text)
    return _resolve_inside(reference[1], install_dir) if reference else None


def _find_mentions(value: str, install_dir: Path) -> list[Path]:
    """Return every `%INSTALLDIR%\\<path>` a field mentions, each read up to the next quote or variable.

    A mention may leave the game. One that is the game directory, or a directory that holds it, is not kept.
    """
    targets = [_follow(reference[1], install_dir) for reference in _INSTALL_DIR_REFERENCE.finditer(value)]
    return [target for target in targets if target is not None and target not in (install_dir, *install_dir.parents)]


def _real_location(program: Path, install_dir: Path) -> Path:
    """Return where the program really is, in terms of install_dir.

    A place inside the game is given as a path under install_dir. The game directory itself, or one that holds
    it, is install_dir. A place elsewhere leaves the program its own name.
    """
    real_install_dir = Path(os.path.realpath(install_dir))
    real_program = Path(os.path.realpath(program))
    if real_install_dir in real_program.parents:
        return install_dir / real_program.relative_to(real_install_dir)
    if real_program in (real_install_dir, *real_install_dir.parents):
        return install_dir
    return program


def _may_be_link(path: Path) -> bool:
    """Whether path is a symlink or junction, or cannot be inspected. An absent path is neither."""
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return is_reparse_stat(path_stat)


def _may_go_through_link(program: Path, install_dir: Path) -> bool:
    """Whether the program, or a directory between it and the game directory, may be a symlink or junction."""
    # realpath returns a link loop unchanged (measured on 3.14.5), so equal paths alone do not rule a link out.
    return any(_may_be_link(component) for component in (program, *program.parents) if install_dir in component.parents)


def _completion_subkey(has_run_keys: list[str | VdfPairs]) -> str | None:
    match has_run_keys:
        case [str() as has_run_key]:
            hive, _, subkey = has_run_key.partition("\\")
            if hive.lower() == _LOCAL_MACHINE_HIVE and subkey:
                return subkey
    return None


def _completion_minimum(minimums: list[str | VdfPairs]) -> int | None:
    match minimums:
        case []:
            return 1
        case [str() as minimum] if _DWORD.fullmatch(minimum):
            return max(int(minimum), 1)
    return None


def _parse_step(name: str, step: VdfPairs, install_dir: Path, *, on_uninstall: bool) -> InstallStep:
    strings = [(key.lower(), value) for key, value in step if isinstance(value, str)]
    programs = [
        program
        for key, value in strings
        if _PROCESS_KEY.fullmatch(key) and (program := _resolve_program(value, install_dir)) is not None
    ]
    real_programs = [_real_location(program, install_dir) for program in programs]
    mentions = [mentioned for _, value in strings for mentioned in _find_mentions(value, install_dir)]
    minimum = _completion_minimum(_values(step, "minimumhasrunvalue"))
    aliased = programs != real_programs or any(_may_go_through_link(program, install_dir) for program in programs)
    settled_by_record = not on_uninstall and minimum is not None and not aliased
    return InstallStep(
        name=name,
        programs=tuple(programs),
        reached=tuple(dict.fromkeys([*programs, *real_programs, *mentions])),
        completion_subkey=_completion_subkey(_values(step, "hasrunkey")) if settled_by_record else None,
        completion_minimum=1 if minimum is None else minimum,
    )


def _read_script(script_path: Path, install_dir: Path) -> list[InstallStep] | None:
    """Return the steps of an install script: none when it is absent, None when it cannot be read as one."""
    try:
        script = _parse_file(script_path)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as read_error:  # fmt: skip  # cosmic-ray (parso) lacks PEP 758
        _logger.debug("Cannot read %s: %s", script_path, read_error)
        return None
    install_scripts = list(_sections(script, "installscript"))
    if not install_scripts:
        return None
    return [
        _parse_step(step_name, step, install_dir, on_uninstall=on_uninstall)
        for install_script in install_scripts
        for section_name, on_uninstall in ((_RUN_SECTION, False), (_UNINSTALL_SECTION, True))
        for section in _sections(install_script, section_name)
        for step_name, step in section
        if not isinstance(step, str)
    ]


def _read_app_states(manifest_path: Path) -> list[VdfPairs]:
    try:
        manifest = _parse_file(manifest_path)
    except (OSError, ValueError) as read_error:  # fmt: skip  # cosmic-ray (parso) lacks PEP 758
        _logger.debug("Cannot read %s: %s", manifest_path, read_error)
        return []
    return list(_sections(manifest, "appstate"))


def _resolve_game_dir(name: str | VdfPairs, common: Path) -> Path | None:
    """Return the game directory an `installdir` names, or None unless it is one plain directory name."""
    if not isinstance(name, str) or not name or PureWindowsPath(name).name != name or name.endswith((".", " ")):
        return None
    return common / name


def read_game_scripts(manifest_path: Path, library: Path) -> GameScripts | None:
    """Return the install steps of the game an app manifest describes, or None when it names no one game."""
    app_states = _read_app_states(manifest_path)
    common = library / "steamapps" / "common"
    install_dirs = {
        _resolve_game_dir(name, common) for app_state in app_states for name in _values(app_state, "installdir")
    }
    install_dir = install_dirs.pop() if len(install_dirs) == 1 else None
    if install_dir is None:
        return None
    steps: list[InstallStep] = []
    unreadable = False
    for app_state in app_states:
        for listed_scripts in _sections(app_state, "installscripts"):
            for _, script_name in listed_scripts:
                script_path = _resolve_inside(script_name, install_dir) if isinstance(script_name, str) else None
                script_steps = _read_script(script_path, install_dir) if script_path else None
                unreadable = unreadable or script_steps is None
                steps.extend(script_steps or [])
    return GameScripts(install_dir=install_dir, steps=tuple(steps), unreadable=unreadable)


def _is_done(step: InstallStep, platform: PlatformAdapter) -> bool | None:
    """Whether a completion record settles the step. None when records cannot be read on this platform."""
    if step.completion_subkey is None:
        return False
    if not platform.has_registry():
        return None
    recorded = platform.read_registry_dword("HKLM", step.completion_subkey, step.name)
    return recorded is not None and recorded >= step.completion_minimum


def collect_installer_evidence(library: Path, platform: PlatformAdapter) -> InstallerEvidence:
    """Read every app manifest of a Steam library and sort what its install scripts refer to."""
    needed: set[Path] = set()
    recorded_as_done: dict[Path, str] = {}
    kept_whole: set[Path] = set()
    described: set[Path] = set()
    every_manifest_read = True
    for manifest_path in sorted((library / "steamapps").glob("appmanifest_*.acf")):
        game = read_game_scripts(manifest_path, library)
        if game is None:
            _logger.info(
                "Cannot tell which game %s describes, so no installer in its library is finished", manifest_path
            )
            every_manifest_read = False
            continue
        described.add(game.install_dir)
        if game.unreadable:
            kept_whole.add(game.install_dir)
        for step in game.steps:
            done = _is_done(step, platform)
            if done is False:
                needed.update(step.reached)
            elif done:
                recorded_as_done.update(dict.fromkeys(step.programs, step.name))
    if not every_manifest_read:
        recorded_as_done.clear()
        common = library / "steamapps" / "common"
        kept_whole.update(game_dir for game_dir in list_subdirs(common) if game_dir not in described)
    kept = InstallerEvidence(needed=frozenset(needed), finished={}, kept_whole=frozenset(kept_whole))
    finished = {program: step_name for program, step_name in recorded_as_done.items() if not kept.protects(program)}
    _logger.debug("Install scripts in %s: %d needed, %d finished", library, len(needed), len(finished))
    return replace(kept, finished=finished)
