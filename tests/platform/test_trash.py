import ctypes
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from assertpy2 import assert_that

from steamcleaner.platform.base import TrashRefusedError
from steamcleaner.platform.linux import LinuxAdapter

if TYPE_CHECKING:
    from collections.abc import Callable

ONLY_WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="the Recycle Bin is asked through the Windows shell")
MEGABYTE = 1024 * 1024
BIN_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume\{volume}"
EXPLORER_POLICIES = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
PLENTY = 10**12
SHELL_SECONDS = 30


def _call_bounded[Result](function: Callable[..., Result], *arguments: object) -> Result:
    """Run a call that reaches the shell in a daemon thread: a shell that never answers fails the test, not hangs it."""
    results: list[Result] = []
    failures: list[Exception] = []

    def run() -> None:
        try:
            results.append(function(*arguments))
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(SHELL_SECONDS)
    if failures:
        raise failures[0]
    assert results, f"the shell did not answer in {SHELL_SECONDS} seconds"
    return results[0]


class TestTrashOffWindows:
    def test_trash_is_expected_to_keep_an_item_of_any_size(self, tmp_path: Path):
        assert_that(LinuxAdapter().keeps_trash(tmp_path, 10**15)).is_true()

    def test_move_goes_through_send2trash_and_reports_the_item_as_held(self, tmp_path: Path):
        with patch("steamcleaner.platform.base.send2trash") as mock_trash:
            held = LinuxAdapter().send_to_trash(tmp_path / "junk")

        mock_trash.assert_called_once_with(str(tmp_path / "junk"))
        assert_that(held).is_true()

    def test_failure_of_the_move_is_passed_on(self, tmp_path: Path):
        with patch("steamcleaner.platform.base.send2trash", side_effect=OSError("no trash directory")):
            assert_that(LinuxAdapter().send_to_trash).raises(OSError).when_called_with(tmp_path / "junk").is_equal_to(
                "no trash directory"
            )


@ONLY_WINDOWS
class TestRecycleBinForecast:
    @staticmethod
    def _stub(
        monkeypatch,
        *,
        numbers: dict[str, int],
        held: int | None = 0,
        volume_id: str | None = "{volume}",
        volume_bytes: int = 2000,
    ) -> list[tuple[str, str]]:
        from steamcleaner.platform import recycle_bin  # Windows-only module

        asked: list[tuple[str, str]] = []

        def read_number(hive: int, subkey: str, name: str) -> int | None:
            asked.append((subkey, name))
            return numbers.get(name)

        monkeypatch.setattr(recycle_bin, "_read_number", read_number)
        monkeypatch.setattr(recycle_bin, "_measure_bin", lambda volume_root: held)
        monkeypatch.setattr(recycle_bin, "_find_volume_id", lambda volume_root: volume_id)
        monkeypatch.setattr(recycle_bin.shutil, "disk_usage", lambda volume_root: SimpleNamespace(total=volume_bytes))
        return asked

    @pytest.mark.parametrize(
        ("numbers", "held", "room"),
        [
            ({"MaxCapacity": 59}, 0, 59 * MEGABYTE),
            ({"MaxCapacity": 59}, 10 * MEGABYTE, 49 * MEGABYTE),
            ({"MaxCapacity": 59}, 59 * MEGABYTE, 0),
            ({"MaxCapacity": 59}, 70 * MEGABYTE, 0),
            ({"MaxCapacity": 59, "NukeOnDelete": 0}, 0, 59 * MEGABYTE),
            ({"MaxCapacity": 59, "NukeOnDelete": 1}, 0, None),
            ({"MaxCapacity": 59, "NoRecycleFiles": 1}, 0, None),
            ({"MaxCapacity": 59, "NoRecycleFiles": 0}, 0, 59 * MEGABYTE),
            ({"MaxCapacity": 59, "RecycleBinSize": 10}, 0, None),
            ({"MaxCapacity": 59}, None, None),
            ({}, 0, 100),
            ({}, 30, 70),
            ({}, 130, 0),
            ({"NukeOnDelete": 1}, 0, None),
        ],
        ids=[
            "empty-bin",
            "bin-holds-some",
            "bin-full",
            "bin-past-its-size",
            "kept",
            "deletes-at-once",
            "policy-turns-it-off",
            "policy-unset",
            "policy-sizes-it",
            "no-bin",
            "nobody-sized-it",
            "nobody-sized-it-and-it-holds-some",
            "nobody-sized-it-and-it-is-past-the-guess",
            "at-once-unsized",
        ],
    )
    def test_room_is_what_the_bin_takes_beside_what_it_holds(
        self, tmp_path: Path, monkeypatch, numbers: dict[str, int], held: int | None, room: int | None
    ):
        from steamcleaner.platform.recycle_bin import find_room  # Windows-only module

        self._stub(monkeypatch, numbers=numbers, held=held)

        assert_that(find_room(tmp_path)).is_equal_to(room)

    def test_settings_are_read_from_the_key_of_the_volume_and_the_policies_from_both_hives(
        self, tmp_path: Path, monkeypatch
    ):
        from steamcleaner.platform.recycle_bin import find_room  # Windows-only module

        asked = self._stub(monkeypatch, numbers={"MaxCapacity": 59})

        find_room(tmp_path)

        assert_that(asked).is_equal_to(
            [
                (EXPLORER_POLICIES, "NoRecycleFiles"),
                (EXPLORER_POLICIES, "RecycleBinSize"),
                (EXPLORER_POLICIES, "NoRecycleFiles"),
                (EXPLORER_POLICIES, "RecycleBinSize"),
                (BIN_SETTINGS, "NukeOnDelete"),
                (BIN_SETTINGS, "MaxCapacity"),
            ]
        )

    def test_bin_is_not_measured_where_a_policy_rules_it(self, tmp_path: Path, monkeypatch):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        self._stub(monkeypatch, numbers={"NoRecycleFiles": 1})
        measured: list[str] = []
        monkeypatch.setattr(recycle_bin, "_measure_bin", measured.append)

        assert_that(recycle_bin.find_room(tmp_path)).is_none()
        assert_that(measured).is_empty()

    def test_volume_without_an_identifier_is_taken_at_a_twentieth_of_its_size(self, tmp_path: Path, monkeypatch):
        from steamcleaner.platform.recycle_bin import find_room  # Windows-only module

        asked = self._stub(monkeypatch, numbers={"MaxCapacity": 59, "NukeOnDelete": 1}, volume_id=None)
        asked.clear()

        assert_that(find_room(tmp_path)).is_equal_to(100)
        assert_that({subkey for subkey, _ in asked}).is_equal_to({EXPLORER_POLICIES})

    def test_bin_nobody_sized_on_a_volume_that_cannot_be_measured_keeps_nothing(self, tmp_path: Path, monkeypatch):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        self._stub(monkeypatch, numbers={})

        def fail(volume_root: str) -> None:
            raise OSError("the device is not ready")

        monkeypatch.setattr(recycle_bin.shutil, "disk_usage", fail)

        assert_that(recycle_bin.find_room(tmp_path)).is_none()

    @pytest.mark.parametrize(
        ("stored", "read"),
        [(1, 1), (0, 0), ("1", None), (FileNotFoundError("no such value"), None)],
        ids=["one", "zero", "text", "absent"],
    )
    def test_only_a_number_is_read_from_the_registry(self, monkeypatch, stored: object, read: int | None):
        import winreg  # Windows-only module

        from steamcleaner.platform import recycle_bin

        def query(key: object, name: str) -> tuple[object, int]:
            if isinstance(stored, OSError):
                raise stored
            return stored, winreg.REG_DWORD

        monkeypatch.setattr(recycle_bin.winreg, "QueryValueEx", query)

        number = recycle_bin._read_number(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows", "Anything")

        assert_that(number).is_equal_to(read)

    def test_value_that_is_there_and_cannot_be_read_is_an_error_not_an_absence(self, monkeypatch):
        import winreg  # Windows-only module

        from steamcleaner.platform import recycle_bin

        def deny(key: object, name: str) -> tuple[object, int]:
            raise PermissionError("Access is denied")

        monkeypatch.setattr(recycle_bin.winreg, "QueryValueEx", deny)

        read = assert_that(recycle_bin._read_number).raises(PermissionError)
        read.when_called_with(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows", "Anything")

    @pytest.mark.parametrize("unreadable", ["NoRecycleFiles", "RecycleBinSize", "NukeOnDelete", "MaxCapacity"])
    def test_setting_that_cannot_be_read_means_no_room_is_known(self, tmp_path: Path, monkeypatch, unreadable: str):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        self._stub(monkeypatch, numbers={"MaxCapacity": 59})

        def read_number(hive: int, subkey: str, name: str) -> int | None:
            if name == unreadable:
                raise PermissionError("Access is denied")
            return {"MaxCapacity": 59}.get(name)

        monkeypatch.setattr(recycle_bin, "_read_number", read_number)

        assert_that(recycle_bin.find_room(tmp_path)).is_none()

    def test_key_that_does_not_exist_reads_as_nothing(self):
        import winreg  # Windows-only module

        from steamcleaner.platform.recycle_bin import _read_number

        assert_that(_read_number(winreg.HKEY_CURRENT_USER, r"Software\SteamCleaner\No such key", "Value")).is_none()

    @pytest.mark.parametrize(
        ("room", "size", "is_folder", "hard_links", "kept"),
        [
            (100, 100, False, True, True),
            (100, 101, False, True, False),
            (100, 0, False, True, True),
            (0, 0, False, True, True),
            (None, 0, False, True, False),
            (100, 10, False, False, False),
            (100, 10, True, False, True),
            (100, 101, True, True, False),
        ],
        ids=[
            "fits-exactly",
            "one-byte-over",
            "empty",
            "empty-into-a-full-bin",
            "bin-keeps-nothing",
            "file-no-hard-links",
            "folder-no-hard-links",
            "folder-too-big",
        ],
    )
    def test_item_is_expected_in_the_bin_when_there_is_room_and_a_file_can_be_held_by_a_second_name(
        self, tmp_path: Path, monkeypatch, room: int | None, size: int, is_folder: bool, hard_links: bool, kept: bool
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        item = tmp_path / "item"
        if is_folder:
            item.mkdir()
        else:
            item.write_bytes(b"x")
        monkeypatch.setattr(recycle_bin, "find_room", lambda path: room)
        monkeypatch.setattr(recycle_bin, "_supports_hard_links", lambda volume_root: hard_links)

        assert_that(recycle_bin.forecast_keeps(item, size)).is_equal_to(kept)

    def test_volume_of_the_tests_takes_hard_links_and_has_a_bin_that_can_be_measured(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        def ask() -> tuple[bool, bool, int | None]:
            volume_root = recycle_bin._find_volume_root(tmp_path)
            assert volume_root is not None
            return (
                recycle_bin._supports_hard_links(volume_root),
                recycle_bin._supports_hard_links("Z:\\no such volume\\"),
                recycle_bin._measure_bin(volume_root),
            )

        hard_links, hard_links_nowhere, held = _call_bounded(ask)

        assert_that((hard_links, hard_links_nowhere)).is_equal_to((True, False))
        assert_that(held).is_instance_of(int).is_greater_than_or_equal_to(0)

    @pytest.mark.parametrize("kept", [True, False], ids=["kept", "not-kept"])
    def test_adapter_asks_the_forecast_of_the_bin(self, windows_adapter, tmp_path: Path, kept: bool):
        with patch("steamcleaner.platform.windows.forecast_keeps", return_value=kept) as forecast:
            assert_that(windows_adapter.keeps_trash(tmp_path, 700)).is_equal_to(kept)

        forecast.assert_called_once_with(tmp_path, 700)

    @pytest.mark.parametrize("held", [True, False], ids=["held", "not-held"])
    def test_adapter_passes_on_what_the_shell_said_of_the_item(self, windows_adapter, tmp_path: Path, held: bool):
        with patch("steamcleaner.platform.windows.recycle", return_value=held) as recycle:
            assert_that(windows_adapter.send_to_trash(tmp_path)).is_equal_to(held)

        recycle.assert_called_once_with(tmp_path)

    def test_network_share_has_no_recycle_bin(self):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        share = Path(f"//localhost/{Path.home().drive[0]}$/Windows")
        if not share.is_dir():
            pytest.skip("the administrative share of the system drive is not reachable")

        assert_that(_call_bounded(recycle_bin._measure_bin, f"\\\\localhost\\{Path.home().drive[0]}$\\")).is_none()
        assert_that(_call_bounded(recycle_bin.find_room, share)).is_none()


@ONLY_WINDOWS
class TestRecycle:
    @staticmethod
    def _make_junk(tmp_path: Path) -> Path:
        junk = tmp_path / "redist"
        junk.mkdir()
        (junk / "setup.exe").write_bytes(b"x" * 2000)
        return junk

    @staticmethod
    def _make_dump(tmp_path: Path, payload: bytes = b"what the dump held") -> Path:
        (tmp_path / "work").mkdir()
        (tmp_path / "bin").mkdir()
        dump = tmp_path / "work" / "crash.dmp"
        dump.write_bytes(payload)
        return dump

    @staticmethod
    def _held_in(directory: Path) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in directory.iterdir()}

    @staticmethod
    def _names_in(directory: Path) -> list[str]:
        return sorted(entry.name for entry in directory.iterdir())

    @staticmethod
    def _move_to_the_bin(path: Path) -> bool:
        path.rename(path.parents[1] / "bin" / "$R1")
        return True

    @pytest.mark.parametrize("kind", ["folder", "file"])
    def test_item_goes_to_the_bin_or_stays_where_the_bin_would_not_keep_it(
        self, windows_adapter, tmp_path: Path, kind: str
    ):
        from steamcleaner.platform.recycle_bin import find_room  # Windows-only module

        junk = self._make_junk(tmp_path)
        item = junk if kind == "folder" else junk / "setup.exe"

        if _call_bounded(find_room, item) is None:
            assert_that(_call_bounded).raises(TrashRefusedError).when_called_with(windows_adapter.send_to_trash, item)
            assert_that((junk / "setup.exe").read_bytes()).is_equal_to(b"x" * 2000)
            assert_that(self._names_in(junk)).is_equal_to(["setup.exe"])
        else:
            assert_that(_call_bounded(windows_adapter.send_to_trash, item)).is_true()
            assert_that(str(item)).does_not_exist()
            assert_that(self._names_in(item.parent)).is_empty()

    @pytest.mark.parametrize("kind", ["folder", "file"])
    def test_shell_is_stopped_where_it_would_delete_for_good(self, tmp_path: Path, kind: str):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        junk = self._make_junk(tmp_path)
        shared = Path(f"//localhost/{junk.drive[0]}$" + str(junk)[2:])
        if not shared.is_dir():
            pytest.skip("the administrative share of this drive is not reachable")
        item = shared if kind == "folder" else shared / "setup.exe"

        with patch.object(recycle_bin, "find_room", return_value=PLENTY):
            refusal = assert_that(_call_bounded).raises(TrashRefusedError).when_called_with(recycle_bin.recycle, item)
            refusal.is_equal_to("the Recycle Bin would not keep it")

        assert_that((junk / "setup.exe").read_bytes()).is_equal_to(b"x" * 2000)
        assert_that(self._names_in(junk)).is_equal_to(["setup.exe"])

    @pytest.mark.parametrize(("room", "kind"), [(1999, "folder"), (1999, "file"), (None, "folder"), (None, "file")])
    def test_item_the_bin_has_no_room_for_is_refused_before_the_shell_is_asked(
        self, tmp_path: Path, room: int | None, kind: str
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        junk = self._make_junk(tmp_path)
        item = junk if kind == "folder" else junk / "setup.exe"

        with (
            patch.object(recycle_bin, "find_room", return_value=room),
            patch.object(recycle_bin.os, "link") as link,
            patch.object(recycle_bin, "_delete_through_shell") as shell,
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(item).is_equal_to(
                "the Recycle Bin would not keep it"
            )

        link.assert_not_called()
        shell.assert_not_called()
        assert_that(self._names_in(junk)).is_equal_to(["setup.exe"])

    def test_folder_that_fills_the_room_exactly_is_handed_to_the_shell(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        junk = self._make_junk(tmp_path)

        with (
            patch.object(recycle_bin, "find_room", return_value=2000),
            patch.object(recycle_bin, "_delete_through_shell", return_value=True) as shell,
        ):
            assert_that(recycle_bin.recycle(junk)).is_true()

        shell.assert_called_once_with(junk)

    def test_file_that_fills_the_room_exactly_is_handed_to_the_shell(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path, b"x" * 2000)

        with (
            patch.object(recycle_bin, "find_room", return_value=2000),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=self._move_to_the_bin) as shell,
        ):
            assert_that(recycle_bin.recycle(dump)).is_true()

        shell.assert_called_once_with(dump)

    def test_second_name_goes_once_the_bin_holds_the_file(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)
        names_during: list[int] = []

        def take(path: Path) -> bool:
            names_during.append(path.stat().st_nlink)
            return self._move_to_the_bin(path)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=take),
        ):
            assert_that(recycle_bin.recycle(dump)).is_true()

        assert_that(names_during).is_equal_to([2])
        assert_that(self._names_in(dump.parent)).is_empty()
        assert_that(self._held_in(tmp_path / "bin")).is_equal_to({"$R1": b"what the dump held"})
        assert_that((tmp_path / "bin" / "$R1").stat().st_nlink).is_equal_to(1)

    def test_file_the_shell_deletes_for_good_is_put_back_from_its_second_name(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def delete_for_good(path: Path) -> bool:
            path.unlink()
            return False

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=delete_for_good),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump).is_equal_to(
                "the Recycle Bin would not keep it"
            )

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})
        assert_that(dump.stat().st_nlink).is_equal_to(1)

    def test_file_the_shell_calls_recycled_without_a_place_in_the_bin_is_put_back(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def delete_and_call_it_recycled(path: Path) -> bool:
            path.unlink()
            return True

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=delete_and_call_it_recycled),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump)

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})

    def test_file_the_shell_calls_recycled_while_it_is_still_under_its_name_is_not_called_trashed(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", return_value=True),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump)

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})
        assert_that(dump.stat().st_nlink).is_equal_to(1)

    @pytest.mark.parametrize("shell_says_kept", [False, True], ids=["deleted-for-good", "called-recycled"])
    def test_file_with_another_name_of_its_own_is_not_taken_for_one_in_the_bin(
        self, tmp_path: Path, shell_says_kept: bool
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)
        os.link(dump, tmp_path / "another-name.dmp")

        def delete(path: Path) -> bool:
            path.unlink()
            return shell_says_kept

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=delete),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump)

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})
        assert_that(dump.stat().st_nlink).is_equal_to(2)

    def test_file_that_kept_its_names_is_not_called_trashed_unless_the_shell_says_so(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def another_program_moves_it_away(path: Path) -> bool:
            path.rename(tmp_path / "moved-away.dmp")
            return False

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=another_program_moves_it_away),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump)

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})

    def test_file_another_program_swaps_in_right_after_the_second_name_is_made_stops_the_move(
        self, tmp_path: Path, monkeypatch
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)
        real_link = os.link

        def link_then_another_program_swaps(source: Path, second_name: Path) -> None:
            real_link(source, second_name)
            source.unlink()
            source.write_bytes(b"another program's file")

        monkeypatch.setattr(recycle_bin.os, "link", link_then_another_program_swaps)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell") as shell,
        ):
            assert_that(recycle_bin.recycle).raises(OSError).when_called_with(dump).starts_with(
                "another file took its name, the file itself is kept as crash.dmp."
            )

        shell.assert_not_called()
        held = self._held_in(dump.parent)
        assert_that(held["crash.dmp"]).is_equal_to(b"another program's file")
        assert_that(sorted(held.values())).is_equal_to([b"another program's file", b"what the dump held"])

    def test_file_another_program_swaps_in_before_the_shell_acts_does_not_cost_the_chosen_one(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def swap_then_recycle_the_other_file(path: Path) -> bool:
            path.unlink()
            path.write_bytes(b"another program's file")
            return self._move_to_the_bin(path)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=swap_then_recycle_the_other_file),
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump)

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})
        assert_that(self._held_in(tmp_path / "bin")).is_equal_to({"$R1": b"another program's file"})

    def test_file_another_program_writes_after_the_bin_took_the_chosen_one_is_left_alone(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def recycle_then_another_program_writes(path: Path) -> bool:
            self._move_to_the_bin(path)
            path.write_bytes(b"another program's file")
            return True

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=recycle_then_another_program_writes),
        ):
            assert_that(recycle_bin.recycle(dump)).is_true()

        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"another program's file"})
        assert_that(self._held_in(tmp_path / "bin")).is_equal_to({"$R1": b"what the dump held"})

    def test_file_another_program_writes_where_the_deleted_one_was_is_not_overwritten(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        def delete_then_another_program_writes(path: Path) -> bool:
            path.unlink()
            path.write_bytes(b"another program's file")
            return False

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=delete_then_another_program_writes),
        ):
            assert_that(recycle_bin.recycle).raises(OSError).when_called_with(dump).starts_with(
                "another file took its name, the file itself is kept as crash.dmp."
            )

        held = self._held_in(dump.parent)
        assert_that(held["crash.dmp"]).is_equal_to(b"another program's file")
        assert_that(sorted(held.values())).is_equal_to([b"another program's file", b"what the dump held"])

    def test_name_is_given_back_by_a_rename_that_refuses_a_file_already_there(self, tmp_path: Path, monkeypatch):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)
        guard = dump.with_name("crash.dmp.guard")
        os.link(dump, guard)
        dump.unlink()
        real_rename = os.rename

        def another_program_writes_just_before(source: Path, destination: Path) -> None:
            destination.write_bytes(b"another program's file")
            real_rename(source, destination)

        monkeypatch.setattr(recycle_bin.os, "rename", another_program_writes_just_before)

        settled = assert_that(recycle_bin._settle_second_name).raises(OSError)
        settled.when_called_with(dump, guard, kept=False, names=2).is_equal_to(
            "another file took its name, the file itself is kept as crash.dmp.guard"
        )
        assert_that(self._held_in(dump.parent)).is_equal_to(
            {"crash.dmp": b"another program's file", "crash.dmp.guard": b"what the dump held"}
        )

    @pytest.mark.parametrize(
        "failure",
        [TrashRefusedError("the Recycle Bin would not keep it"), PermissionError("the file is in use")],
        ids=["refused", "failed"],
    )
    def test_file_the_shell_left_alone_loses_only_its_second_name(self, tmp_path: Path, failure: OSError):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=failure),
        ):
            assert_that(recycle_bin.recycle).raises(type(failure)).when_called_with(dump).is_equal_to(str(failure))

        assert_that(dump.stat().st_nlink).is_equal_to(1)
        assert_that(self._held_in(dump.parent)).is_equal_to({"crash.dmp": b"what the dump held"})

    def test_file_that_cannot_get_a_second_name_is_not_handed_to_the_shell(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        dump = self._make_dump(tmp_path)

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin.os, "link", side_effect=OSError(1, "Incorrect function")),
            patch.object(recycle_bin, "_delete_through_shell") as shell,
        ):
            assert_that(recycle_bin.recycle).raises(TrashRefusedError).when_called_with(dump).is_equal_to(
                "it cannot be held by a second name while the Recycle Bin takes it"
            )

        shell.assert_not_called()
        assert_that(self._names_in(dump.parent)).is_equal_to(["crash.dmp"])

    @pytest.mark.parametrize("held", [True, False], ids=["held", "not-held"])
    def test_folder_that_is_gone_is_reported_as_the_shell_said(self, tmp_path: Path, held: bool):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        junk = self._make_junk(tmp_path)

        def take(path: Path) -> bool:
            (path / "setup.exe").unlink()
            path.rmdir()
            return held

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin.os, "link") as link,
            patch.object(recycle_bin, "_delete_through_shell", side_effect=take) as shell,
        ):
            assert_that(recycle_bin.recycle(junk)).is_equal_to(held)

        link.assert_not_called()
        shell.assert_called_once_with(junk)

    @pytest.mark.parametrize("inspectable", [True, False], ids=["still-there", "cannot-be-inspected"])
    def test_folder_the_shell_calls_gone_is_a_failure_unless_it_is_seen_to_be_gone(
        self, tmp_path: Path, monkeypatch, inspectable: bool
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        junk = self._make_junk(tmp_path)
        real_lstat = Path.lstat

        def deny_the_folder(path: Path) -> os.stat_result:
            if path == junk:
                raise PermissionError("Access is denied")
            return real_lstat(path)

        def call_it_gone(path: Path) -> bool:
            if not inspectable:
                monkeypatch.setattr(Path, "lstat", deny_the_folder)
                monkeypatch.setattr(recycle_bin.os.path, "lexists", lambda path: False)
            return False

        with (
            patch.object(recycle_bin, "find_room", return_value=PLENTY),
            patch.object(recycle_bin, "_delete_through_shell", side_effect=call_it_gone),
        ):
            assert_that(recycle_bin.recycle).raises(OSError).when_called_with(junk).is_equal_to(
                "the shell left it where it was"
            )

        monkeypatch.undo()
        assert_that(self._names_in(junk)).is_equal_to(["setup.exe"])

    def test_path_that_is_not_there_is_an_error_of_its_own(self, tmp_path: Path):
        from steamcleaner.platform.recycle_bin import recycle  # Windows-only module

        assert_that(recycle).raises(FileNotFoundError).when_called_with(tmp_path / "gone")


@ONLY_WINDOWS
class TestShellSink:
    RECYCLES = 0x282
    DELETES_FOR_GOOD = 0x202
    TARGET = 0x1000
    CHILD = 0x2000
    IN_THE_BIN = 0x3000
    DONE = 0x00270008
    FAILED = -0x7FFFBFFB

    def _watch(self):
        from steamcleaner.platform.recycle_bin import _DeleteWatcher  # Windows-only module

        return _DeleteWatcher(lambda announced: announced == self.TARGET)

    def test_delete_the_shell_would_recycle_is_let_through(self):
        watcher = self._watch()

        assert_that(watcher._before_delete(0, self.RECYCLES, self.TARGET)).is_equal_to(0)
        assert_that(watcher.refused).is_false()

    @pytest.mark.parametrize("announced", [TARGET, CHILD], ids=["target", "what-it-holds"])
    def test_delete_the_shell_would_make_for_good_is_aborted(self, announced: int):
        watcher = self._watch()

        assert_that(watcher._before_delete(0, self.DELETES_FOR_GOOD, announced) & 0xFFFFFFFF).is_equal_to(0x80004004)
        assert_that(watcher.refused).is_true()

    @pytest.mark.parametrize(
        ("recycled_item", "kept"), [(IN_THE_BIN, True), (None, False)], ids=["in-the-bin", "nowhere"]
    )
    def test_target_whose_delete_succeeded_is_kept_when_the_shell_names_it_in_the_bin(
        self, recycled_item: int | None, kept: bool
    ):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._after_delete(0, self.RECYCLES, self.TARGET, self.DONE, recycled_item)

        assert_that(_read_outcome(watcher, 0, aborted=False)).is_equal_to(kept)

    @pytest.mark.parametrize("recycled_item", [IN_THE_BIN, None], ids=["named-in-the-bin", "nowhere"])
    def test_target_whose_own_delete_failed_is_a_failure_though_the_operation_ended_well(
        self, recycled_item: int | None
    ):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._after_delete(0, self.RECYCLES, self.TARGET, self.FAILED, recycled_item)

        outcome = assert_that(_read_outcome).raises(OSError).when_called_with(watcher, 0, aborted=False)
        outcome.is_equal_to("the shell could not move it to the Recycle Bin (0x80004005)")

    def test_operation_that_never_reported_the_target_is_a_failure(self):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._after_delete(0, self.RECYCLES, self.CHILD, self.DONE, self.IN_THE_BIN)

        outcome = assert_that(_read_outcome).raises(OSError).when_called_with(watcher, 0, aborted=False)
        outcome.is_equal_to("the shell did not move it to the Recycle Bin")

    def test_operation_the_shell_aborted_is_a_failure(self):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._after_delete(0, self.RECYCLES, self.TARGET, self.DONE, self.IN_THE_BIN)

        outcome = assert_that(_read_outcome).raises(OSError).when_called_with(watcher, 0, aborted=True)
        outcome.is_equal_to("the shell did not move it to the Recycle Bin")

    def test_operation_that_failed_is_a_failure(self):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._after_delete(0, self.RECYCLES, self.TARGET, self.DONE, self.IN_THE_BIN)

        outcome = assert_that(_read_outcome).raises(OSError).when_called_with(watcher, self.FAILED, aborted=False)
        outcome.is_equal_to("the shell could not move it to the Recycle Bin (0x80004005)")

    def test_refusal_is_told_before_any_other_failure(self):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        watcher._before_delete(0, self.DELETES_FOR_GOOD, self.CHILD)

        outcome = assert_that(_read_outcome).raises(TrashRefusedError)
        outcome.when_called_with(watcher, self.FAILED, aborted=True).is_equal_to("the Recycle Bin would not keep it")

    @pytest.mark.parametrize("child_first", [True, False], ids=["child-first", "target-first"])
    def test_fate_of_the_target_is_read_from_its_own_callback_in_any_order(self, child_first: bool):
        from steamcleaner.platform.recycle_bin import _read_outcome  # Windows-only module

        watcher = self._watch()
        calls = [(self.CHILD, self.IN_THE_BIN), (self.TARGET, None)]

        for item, recycled_item in calls if child_first else reversed(calls):
            watcher._after_delete(0, self.RECYCLES, item, self.DONE, recycled_item)

        assert_that(_read_outcome(watcher, 0, aborted=False)).is_false()

    @pytest.mark.parametrize(
        ("answer", "order", "same"),
        [(0, 0, True), (1, 1, False), (0, 1, False), (FAILED, 0, False)],
        ids=["same", "another", "same-by-answer-only", "comparison-failed"],
    )
    def test_item_is_the_requested_one_only_when_the_comparison_succeeds_and_finds_no_difference(
        self, answer: int, order: int, same: bool
    ):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        def compare(requested, announced, hint, found) -> int:
            ctypes.cast(found, ctypes.POINTER(ctypes.c_int))[0] = order
            return answer

        with patch.object(recycle_bin, "_method", return_value=compare):
            assert_that(recycle_bin._is_same_item(self.CHILD, ctypes.c_void_p(self.TARGET))).is_equal_to(same)

    def test_shell_tells_an_item_from_another_and_from_itself_named_twice(self, tmp_path: Path):
        from steamcleaner.platform import recycle_bin  # Windows-only module

        (tmp_path / "one.dmp").write_bytes(b"x")
        (tmp_path / "two.dmp").write_bytes(b"x")

        def name(path: Path) -> ctypes.c_void_p:
            item = ctypes.c_void_p()
            recycle_bin._check(
                recycle_bin._SHELL32.SHCreateItemFromParsingName(
                    str(path), None, ctypes.byref(recycle_bin._IID_SHELL_ITEM), ctypes.byref(item)
                )
            )
            return item

        def compare() -> tuple[bool, bool]:
            recycle_bin._check(recycle_bin._OLE32.CoInitializeEx(None, recycle_bin._APARTMENT_THREADED_NO_DDE))
            try:
                requested = name(tmp_path / "one.dmp")
                again = name(tmp_path / "one.dmp")
                other = name(tmp_path / "two.dmp")
                assert again.value is not None
                assert other.value is not None
                answers = (
                    recycle_bin._is_same_item(again.value, requested),
                    recycle_bin._is_same_item(other.value, requested),
                )
                for item in (requested, again, other):
                    recycle_bin._method(item, recycle_bin._RELEASE, recycle_bin._TAKES_NOTHING)(item)
                return answers
            finally:
                recycle_bin._OLE32.CoUninitialize()

        assert_that(_call_bounded(compare)).is_equal_to((True, False))

    @pytest.mark.parametrize(
        ("interface", "result"),
        [
            ("00000000-0000-0000-c000-000000000046", 0),
            ("04b0f1a7-9490-44bc-96e1-4296a31252e2", 0),
            ("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8", 0x80004002),
        ],
        ids=["IUnknown", "IFileOperationProgressSink", "another-interface"],
    )
    def test_sink_answers_for_its_own_interfaces_only(self, interface: str, result: int):
        import uuid

        from steamcleaner.platform.recycle_bin import _DeleteWatcher, _Guid  # Windows-only module

        asked = ctypes.pointer(_Guid.from_buffer_copy(uuid.UUID(interface).bytes_le))
        given = ctypes.pointer(ctypes.c_void_p(0xDEAD))

        answer = _DeleteWatcher._query_interface(0x1234, asked, given)

        assert_that(answer & 0xFFFFFFFF).is_equal_to(result)
        assert_that(given[0]).is_equal_to(None if result else 0x1234)
