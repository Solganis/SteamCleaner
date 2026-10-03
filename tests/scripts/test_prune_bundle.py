import importlib.util
import sys
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from assertpy2 import assert_that

if TYPE_CHECKING:
    from collections.abc import Mapping

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "prune_bundle.py"


@pytest.fixture(scope="module")
def prune_bundle():
    spec = importlib.util.spec_from_file_location("prune_bundle", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TCL_TK_FILES = MappingProxyType(
    {"DLLs/tcl90.dll": 50, "DLLs/tcl9tk90.dll": 40, "DLLs/libtommath.dll": 8, "DLLs/libffi-8.dll": 3}
)


def _make_bundle(root: Path, files: Mapping[str, int]) -> Path:
    """Create a bundle holding the given files, each as its size in bytes."""
    bundle = root / "windows"
    (bundle / "Lib").mkdir(parents=True)
    (bundle / "DLLs").mkdir()
    for relative_path, size in files.items():
        file_path = bundle / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"\x00" * size)
    return bundle


def _list_files(bundle: Path) -> list[str]:
    return sorted(path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file())


class TestDebugTwins:
    def test_debug_build_beside_its_release_build_is_removed(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(
            tmp_path, {"DLLs/_ssl.pyd": 10, "DLLs/_ssl_d.pyd": 30, "DLLs/ffi.dll": 5, "DLLs/ffi_d.dll": 7}
        )

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(["DLLs/_ssl.pyd", "DLLs/ffi.dll"])
        assert_that(removed_bytes).is_equal_to(37)

    def test_debug_build_with_no_release_build_stays(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, {"DLLs/_only_d.pyd": 30, "DLLs/lone_d.dll": 7})

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(["DLLs/_only_d.pyd", "DLLs/lone_d.dll"])
        assert_that(removed_bytes).is_equal_to(0)

    def test_release_build_whose_name_only_ends_like_a_debug_one_stays(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, {"DLLs/grid.pyd": 10, "DLLs/gri_d.pyd": 10, "DLLs/gri.txt": 1})

        prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(["DLLs/gri.txt", "DLLs/gri_d.pyd", "DLLs/grid.pyd"])

    def test_file_is_taken_for_a_debug_build_by_its_own_name_only(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, {"DLLs/plain.pyd": 10, "DLLs/plain.pyd.pyd": 10, "DLLs/plain.dll.dll": 10})

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(["DLLs/plain.dll.dll", "DLLs/plain.pyd", "DLLs/plain.pyd.pyd"])
        assert_that(removed_bytes).is_equal_to(0)


class TestTclTk:
    def test_libraries_go_when_nothing_in_the_bundle_can_load_them(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, TCL_TK_FILES)

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(["DLLs/libffi-8.dll"])
        assert_that(removed_bytes).is_equal_to(98)

    def test_libraries_stay_in_a_bundle_that_has_tkinter(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, {**TCL_TK_FILES, "DLLs/_tkinter.pyd": 6})

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_length(5)
        assert_that(removed_bytes).is_equal_to(0)


class TestStandardLibrary:
    def test_unused_modules_go_whether_a_package_or_a_single_file(self, tmp_path: Path, prune_bundle):
        files = {
            "Lib/unittest/__init__.pyc": 100,
            "Lib/unittest/mock.pyc": 300,
            "Lib/turtle.pyc": 180,
            "Lib/pdb.py": 20,
            "Lib/sqlite3/__init__.pyc": 16,
            "DLLs/_sqlite3.pyd": 100,
            "DLLs/sqlite3.dll": 1500,
        }
        bundle = _make_bundle(tmp_path, files)

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_empty()
        assert_that(removed_bytes).is_equal_to(2216)

    def test_everything_else_stays(self, tmp_path: Path, prune_bundle):
        kept = {
            "Lib/asyncio/__init__.pyc": 100,
            "Lib/codeop.pyc": 7,
            "Lib/traceback.pyc": 90,
            "Lib/unittest_helpers.pyc": 5,
            "DLLs/_ssl.pyd": 10,
            "DLLs/libcrypto-3.dll": 6000,
            "site-packages/flet/__init__.pyc": 10,
            "steamcleaner.exe": 80,
        }
        bundle = _make_bundle(tmp_path, kept)

        removed_bytes = prune_bundle.prune(bundle)

        assert_that(_list_files(bundle)).is_equal_to(sorted(kept))
        assert_that(removed_bytes).is_equal_to(0)

    def test_every_listed_module_is_one_the_app_was_measured_without(self, prune_bundle):
        kept_by_an_importer = {"codeop", "smtplib", "ftplib", "xmlrpc", "py_compile", "email", "http", "xml"}

        assert_that(set(prune_bundle.UNUSED_STDLIB) & kept_by_an_importer).is_empty()
        assert_that(sorted(prune_bundle.UNUSED_STDLIB)).is_equal_to(list(prune_bundle.UNUSED_STDLIB))


class TestCommandLine:
    def test_pruning_twice_removes_nothing_the_second_time(self, tmp_path: Path, prune_bundle):
        bundle = _make_bundle(tmp_path, {"Lib/turtle.pyc": 180, "DLLs/_ssl.pyd": 10, "DLLs/_ssl_d.pyd": 30})

        assert_that(prune_bundle.prune(bundle)).is_equal_to(210)
        assert_that(prune_bundle.prune(bundle)).is_equal_to(0)

    def test_directory_that_is_not_a_windows_bundle_is_refused(self, tmp_path: Path, prune_bundle):
        (tmp_path / "Lib").mkdir()
        (tmp_path / "Lib" / "turtle.pyc").write_bytes(b"\x00")

        with pytest.raises(SystemExit) as refusal:
            prune_bundle.prune(tmp_path)

        assert_that(str(refusal.value)).contains("not a Windows bundle")
        assert_that(str(tmp_path / "Lib" / "turtle.pyc")).exists()

    def test_main_reports_what_went(self, tmp_path: Path, prune_bundle, monkeypatch, capsys):
        megabyte = 1024 * 1024
        bundle = _make_bundle(tmp_path, {"Lib/turtle.pyc": megabyte, "DLLs/tcl90.dll": megabyte // 2})
        monkeypatch.setattr(sys, "argv", ["prune_bundle.py", str(bundle)])

        prune_bundle.main()

        output = capsys.readouterr().out
        assert_that(output).contains("removed DLLs", "removed Lib", f"Pruned 1.5 MB from {bundle}")
        assert_that(_list_files(bundle)).is_empty()
