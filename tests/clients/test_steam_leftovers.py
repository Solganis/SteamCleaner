import ctypes
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from assertpy2 import assert_that
from helpers import FakePlatformAdapter, serialize_vdf, write_app_manifest

from steamcleaner.clients.steam import SteamClient
from steamcleaner.models.junk import JunkCategory, JunkEntry
from steamcleaner.models.scan_result import reclaimable_bytes
from steamcleaner.scanner.exclusions import ExclusionRegistry
from steamcleaner.utils.fs import walk_files

if TYPE_CHECKING:
    from steamcleaner.utils.vdf import VdfDict

IN_2021 = datetime(2021, 1, 2, 12, tzinfo=UTC).timestamp()
IN_2023 = datetime(2023, 5, 9, 12, tzinfo=UTC).timestamp()


def _make_library(root: Path, name: str = "Steam") -> Path:
    library = root / name
    (library / "steamapps" / "common").mkdir(parents=True)
    return library


def _install(library: Path, app_id: int, install_dir: str) -> Path:
    """Write the app manifest of an installed game and give it one file."""
    write_app_manifest(library, app_id, install_dir)
    return _leave_behind(library, install_dir, {"game.bin": (4000, IN_2023)})


def _leave_behind(library: Path, directory_name: str, files: dict[str, tuple[int, float]]) -> Path:
    """Create a game directory holding the given files, each as (size, time last written)."""
    game_dir = library / "steamapps" / "common" / directory_name
    for relative_path, (size, written) in files.items():
        file_path = game_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"\x00" * size)
        os.utime(file_path, (written, written))
    return game_dir


def _tell_letter_case_apart(directory: Path) -> None:
    """Make a directory keep `Name` and `name` as two entries, or skip the test where it cannot."""
    if sys.platform == "win32":
        subprocess.run(
            ["fsutil.exe", "file", "setCaseSensitiveInfo", str(directory), "enable"], check=False, capture_output=True
        )
    (directory / "probe").mkdir()
    try:
        (directory / "PROBE").mkdir()
    except FileExistsError:
        pytest.skip("this directory cannot be made to tell letter case apart")


def _find_short_name(directory: Path) -> str:
    """Return the 8.3 alias Windows keeps for a directory, or skip the test where there is none."""
    if sys.platform != "win32":
        pytest.skip("8.3 aliases are a Windows filesystem feature")
    buffer = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(directory), buffer, len(buffer))
    short_name = Path(buffer.value).name
    if short_name in {"", directory.name}:
        pytest.skip("this volume keeps no 8.3 alias")
    return short_name


def _make_client(library: Path) -> SteamClient:
    return SteamClient(FakePlatformAdapter(install_path=library), ExclusionRegistry())


def _scan(library: Path) -> list[JunkEntry]:
    return list(_make_client(library).scan_safe())


def _leftover(game_dir: Path, size: int, last_written_on: str) -> JunkEntry:
    label = f"{game_dir.name} (left by an uninstalled game, last written on {last_written_on})"
    return JunkEntry(
        path=game_dir,
        category=JunkCategory.LEFTOVER,
        size_bytes=size,
        client_name="Steam",
        description=label,
        game_root=game_dir,
        display_name=label,
    )


class TestLeftoverGames:
    @pytest.mark.parametrize(
        ("save_written", "cache_written"), [(IN_2021, IN_2023), (IN_2023, IN_2021)], ids=["cache-newest", "save-newest"]
    )
    def test_folder_no_manifest_describes_is_offered_whole_with_its_newest_write(
        self, tmp_path: Path, save_written: float, cache_written: float
    ):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        files = {"save.dat": (3000, save_written), "cache/data.bin": (5000, cache_written)}
        old_game = _leave_behind(library, "Old Game", files)

        assert_that(_scan(library)).is_equal_to([_leftover(old_game, 8000, "2023-05-09")])

    def test_size_is_the_sum_of_every_file_before_the_disk_is_measured(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        files = {"save.dat": (3000, IN_2021), "cache/data.bin": (5000, IN_2021), "cache/more/index": (11, IN_2021)}
        old_game = _leave_behind(library, "Old Game", files)

        assert_that(list(_make_client(library).scan_junk())).is_equal_to([_leftover(old_game, 8011, "2021-01-02")])

    def test_folder_a_manifest_describes_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")

        assert_that(_scan(library)).is_empty()

    def test_library_without_any_manifest_is_not_judged(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})

        assert_that(_scan(library)).is_empty()

    @pytest.mark.parametrize(
        "manifest_text",
        [
            "{",
            '"AppState" { "appid" "9" }',
            '"AppState" { "installdir" "Old Game" "installdir" "Installed Game" }',
            '"AppState" { "installdir" "Old Game\\\\bin" }',
            '"AppState" { "installdir" "Old Game:saves" }',
            '"AppState" { "installdir" "Installed Game" "installdir" "installed game" }',
            '"AppState" { "installdir" "Old\x00Game" }',
        ],
        ids=[
            "unreadable",
            "no-installdir",
            "two-different-installdirs",
            "nested-installdir",
            "installdir-with-a-colon",
            "two-spellings-of-one-installdir",
            "installdir-with-a-control-character",
        ],
    )
    def test_manifest_that_names_no_one_game_stops_the_library_offering_leftovers(
        self, tmp_path: Path, manifest_text: str
    ):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        (library / "steamapps" / "appmanifest_9.acf").write_text(manifest_text, encoding="utf-8")

        assert_that(_scan(library)).is_empty()

    def test_manifest_that_repeats_one_installdir_still_names_one_game(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _leave_behind(library, "Installed Game", {"game.bin": (4000, IN_2023)})
        old_game = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        repeated = '"AppState" { "installdir" "Installed Game" "installdir" "Installed Game" }'
        (library / "steamapps" / "appmanifest_10.acf").write_text(repeated, encoding="utf-8")

        assert_that(_scan(library)).is_equal_to([_leftover(old_game, 3000, "2021-01-02")])

    def test_manifest_that_cannot_be_opened_stops_the_library_offering_leftovers(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        locked = write_app_manifest(library, 9, "Game Behind The Lock")
        read_text = Path.read_text

        def refuse_one_manifest(path: Path, *args, **kwargs):
            if path == locked:
                raise PermissionError(13, "Permission denied", str(path))
            return read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", refuse_one_manifest)

        assert_that(_scan(library)).is_empty()

    def test_manifest_of_a_game_whose_folder_is_gone_does_not_stop_the_library(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        write_app_manifest(library, 20, "Removed By Hand")
        old_game = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})

        assert_that(_scan(library)).is_equal_to([_leftover(old_game, 3000, "2021-01-02")])

    def test_folder_a_manifest_reaches_through_a_link_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        real_folder = _leave_behind(library, "Game Under Its Real Name", {"game.bin": (3000, IN_2021)})
        (library / "steamapps" / "common" / "Linked Name").symlink_to(real_folder, target_is_directory=True)
        write_app_manifest(library, 20, "Linked Name")

        assert_that(_scan(library)).is_empty()

    def test_folder_a_manifest_names_in_another_letter_case_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        if not (library / "steamapps" / "common" / "old game").exists():
            pytest.skip("this filesystem tells letter case apart, so the two names are two folders")
        write_app_manifest(library, 20, "old game")

        assert_that(_scan(library)).is_empty()

    def test_folder_a_manifest_names_by_its_short_alias_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        long_name = _leave_behind(library, "Game Under A Long Name", {"game.bin": (3000, IN_2021)})
        write_app_manifest(library, 20, _find_short_name(long_name))

        assert_that(_scan(library)).is_empty()

    def test_folder_named_like_an_installed_one_but_for_letter_case_is_not_taken_for_it(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _tell_letter_case_apart(library / "steamapps" / "common")
        installed = _install(library, 10, "Old Game")
        left_behind = _leave_behind(library, "old game", {"save.dat": (3000, IN_2021)})

        offered = [str(entry.path) for entry in _scan(library)]

        assert_that(offered).is_equal_to([] if left_behind == installed else [str(left_behind)])

    def test_folders_whose_paths_compare_equal_are_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _tell_letter_case_apart(library / "steamapps" / "common")
        _install(library, 10, "Installed Game")
        capital = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        small = _leave_behind(library, "old game", {"save.dat": (3000, IN_2021)})
        other = _leave_behind(library, "Other Game", {"save.dat": (3000, IN_2021)})

        offered = sorted(str(entry.path) for entry in _scan(library))

        told_apart = [] if capital == small else [capital, small]
        assert_that(offered).is_equal_to(sorted(str(game_dir) for game_dir in [*told_apart, other]))

    def test_folder_the_listing_cannot_read_is_passed_over_alone(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        _leave_behind(library, "Unreadable Game", {"save.dat": (3000, IN_2021)})

        class _DirEntryThatRefuses:
            def __init__(self, entry: os.DirEntry) -> None:
                self.path = entry.path

            def is_dir(self, *, follow_symlinks: bool = True) -> bool:
                raise PermissionError(13, "Permission denied", self.path)

        scandir = os.scandir

        class _Listing:
            def __init__(self, directory: Path) -> None:
                with scandir(directory) as entries:
                    self._entries = [
                        _DirEntryThatRefuses(entry) if entry.name == "Unreadable Game" else entry for entry in entries
                    ]

            def __enter__(self):
                return self

            def __exit__(self, *exc_info: object) -> None:
                pass

            def __iter__(self):
                return iter(self._entries)

        monkeypatch.setattr(os, "scandir", _Listing)

        assert_that(_scan(library)).is_equal_to([_leftover(old_game, 3000, "2021-01-02")])

    def test_library_is_not_judged_when_an_installed_folder_cannot_be_inspected(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        installed = _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        inspect = Path.stat

        def refuse_one_folder(path: Path, **kwargs):
            if path == installed:
                raise PermissionError(13, "Permission denied", str(path))
            return inspect(path, **kwargs)

        monkeypatch.setattr(Path, "stat", refuse_one_folder)

        assert_that(_scan(library)).is_empty()

    def test_folder_is_judged_by_the_manifests_of_its_own_library(self, tmp_path: Path):
        main_library = _make_library(tmp_path)
        second_library = _make_library(tmp_path, "SecondLibrary")
        _install(main_library, 10, "Moved Game")
        _install(second_library, 20, "Other Game")
        left_in_second = _leave_behind(second_library, "Moved Game", {"save.dat": (3000, IN_2021)})
        libraries: VdfDict = {"0": {"path": str(main_library)}, "1": {"path": str(second_library)}}
        folders: VdfDict = {"libraryfolders": libraries}
        (main_library / "steamapps" / "libraryfolders.vdf").write_text(serialize_vdf(folders), encoding="utf-8")

        assert_that(_scan(main_library)).is_equal_to([_leftover(left_in_second, 3000, "2021-01-02")])

    def test_folder_that_holds_nothing_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"empty.cfg": (0, IN_2021)})
        (old_game / "saves").mkdir()

        assert_that(list(_make_client(library).scan_junk())).is_empty()

    def test_folder_that_holds_a_steam_library_of_its_own_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        _install(_make_library(old_game, "InnerLibrary"), 30, "Game Of The Inner Library")

        assert_that(_scan(library)).is_empty()

    def test_linked_folder_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "save.dat").write_bytes(b"\x00" * 3000)
        (library / "steamapps" / "common" / "Linked Game").symlink_to(elsewhere, target_is_directory=True)

        assert_that(_scan(library)).is_empty()

    def test_junk_inside_a_leftover_is_offered_on_its_own_and_counted_once(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"crash.dmp": (900, IN_2021), "save.dat": (100, IN_2023)})

        entries = _scan(library)

        assert_that([(entry.path, entry.category, entry.size_bytes) for entry in entries]).is_equal_to(
            [
                (old_game / "crash.dmp", JunkCategory.CRASH_DUMP, 900),
                (old_game, JunkCategory.LEFTOVER, 1000),
            ]
        )
        assert_that(reclaimable_bytes(entries)).is_equal_to(1000)

    def test_file_that_vanishes_during_the_walk_is_left_out(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"gone.bin": (700, IN_2023), "save.dat": (3000, IN_2021)})
        lstat = Path.lstat

        def lose_one_file(path: Path):
            if path.name == "gone.bin":
                raise FileNotFoundError(2, "No such file or directory", str(path))
            return lstat(path)

        monkeypatch.setattr(Path, "lstat", lose_one_file)

        assert_that(list(_make_client(library).scan_junk())).is_equal_to([_leftover(old_game, 3000, "2021-01-02")])

    @pytest.mark.parametrize(
        ("written", "shown"),
        [(-1.0, "1969-12-31"), (-1e-7, "1969-12-31"), (1e11, "5138-11-16"), (9e11, "an unknown date")],
        ids=["before-1970", "a-moment-before-1970", "past-the-year-3000", "past-any-calendar"],
    )
    def test_newest_write_is_shown_whatever_time_the_file_carries(
        self, tmp_path: Path, monkeypatch, written: float, shown: str
    ):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        lstat = Path.lstat

        def carry_another_time(path: Path):
            return SimpleNamespace(st_size=3000, st_mtime=written) if path.name == "save.dat" else lstat(path)

        monkeypatch.setattr(Path, "lstat", carry_another_time)

        assert_that(list(_make_client(library).scan_junk())).is_equal_to([_leftover(old_game, 3000, shown)])

    def test_cancelling_stops_the_walk_of_a_leftover(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {f"save{number}.dat": (1000, IN_2021) for number in range(6)})
        cancel = threading.Event()
        walked: list[Path] = []

        def cancel_after_the_first_file(root: Path):
            for file_path, size in walk_files(root):
                walked.append(file_path)
                yield file_path, size
                cancel.set()

        monkeypatch.setattr("steamcleaner.clients.steam.walk_files", cancel_after_the_first_file)

        assert_that(list(_make_client(library).scan_safe(cancel))).is_empty()
        assert_that([file_path.parent for file_path in walked]).is_equal_to([old_game, old_game])

    def test_folder_steam_keeps_for_itself_is_not_offered(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Steam Controller Configs", {"1234/config/layout.vdf": (3000, IN_2023)})

        assert_that(_scan(library)).is_empty()


class TestLeftoverIsCheckedAgainBeforeDeletion:
    def test_leftover_still_stands_while_no_manifest_names_it(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        (leftover,) = _scan(library)

        assert_that(_make_client(library).still_offers(leftover)).is_true()

    def test_leftover_no_longer_stands_once_the_game_is_installed_again(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        (leftover,) = _scan(library)

        write_app_manifest(library, 20, "Old Game")

        assert_that(_make_client(library).still_offers(leftover)).is_false()

    def test_leftover_no_longer_stands_once_its_library_cannot_be_judged(self, tmp_path: Path):
        library = _make_library(tmp_path)
        installed_manifest = write_app_manifest(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        (leftover,) = _scan(library)

        installed_manifest.unlink()

        assert_that(_make_client(library).still_offers(leftover)).is_false()

    def test_leftover_no_longer_stands_when_its_library_cannot_be_listed(self, tmp_path: Path, monkeypatch):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        _leave_behind(library, "Old Game", {"save.dat": (3000, IN_2021)})
        (leftover,) = _scan(library)

        def fail_to_list(directory: Path):
            raise OSError(5, "Input/output error", str(directory))

        monkeypatch.setattr("steamcleaner.clients.steam.list_subdirs", fail_to_list)

        assert_that(_make_client(library).still_offers(leftover)).is_false()

    def test_other_junk_stands_whatever_the_manifests_say(self, tmp_path: Path):
        library = _make_library(tmp_path)
        _install(library, 10, "Installed Game")
        old_game = _leave_behind(library, "Old Game", {"crash.dmp": (900, IN_2021)})
        crash_dump, _ = _scan(library)

        write_app_manifest(library, 20, "Old Game")

        assert_that(crash_dump.path).is_equal_to(old_game / "crash.dmp")
        assert_that(_make_client(library).still_offers(crash_dump)).is_true()
