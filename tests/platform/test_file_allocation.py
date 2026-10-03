import ctypes
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from assertpy2 import assert_that

from steamcleaner.platform.base import FileAllocation
from steamcleaner.platform.linux import LinuxAdapter
from steamcleaner.utils.fs import disk_usage

ONLY_POSIX = pytest.mark.skipif(sys.platform == "win32", reason="st_blocks is a POSIX stat field")
ONLY_WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="the Windows adapter calls kernel32")


class TestPosixFileAllocation:
    def test_reads_blocks_identity_and_link_count(self, tmp_path: Path, monkeypatch):
        fake_stat = SimpleNamespace(st_blocks=16, st_dev=7, st_ino=99, st_nlink=2)
        monkeypatch.setattr(Path, "lstat", lambda _path: fake_stat)
        allocation = LinuxAdapter().file_allocation(tmp_path / "setup.exe")
        assert_that(allocation).is_equal_to(FileAllocation(allocated_bytes=8192, file_id=(7, 99), link_count=2))

    @ONLY_POSIX
    def test_sparse_file_holds_less_than_its_length(self, tmp_path: Path):
        sparse = tmp_path / "sparse.bin"
        with sparse.open("wb") as handle:
            handle.truncate(10 * 1024 * 1024)
        assert_that(LinuxAdapter().file_allocation(sparse).allocated_bytes).is_less_than(1024 * 1024)


@ONLY_WINDOWS
class TestWindowsFileAllocation:
    @staticmethod
    def _cluster_bytes(path: Path) -> int:
        sectors_per_cluster = ctypes.c_ulong()
        bytes_per_sector = ctypes.c_ulong()
        ctypes.windll.kernel32.GetDiskFreeSpaceW(
            path.anchor, ctypes.byref(sectors_per_cluster), ctypes.byref(bytes_per_sector), None, None
        )
        return sectors_per_cluster.value * bytes_per_sector.value

    @staticmethod
    def _compressed_bytes(path: Path) -> int:
        """Ask Windows through a different call than the adapter uses what the file holds on disk."""
        high_part = ctypes.c_ulong()
        get_compressed_size = ctypes.windll.kernel32.GetCompressedFileSizeW
        get_compressed_size.restype = ctypes.c_ulong
        low_part = get_compressed_size(str(path), ctypes.byref(high_part))
        return (high_part.value << 32) | low_part

    def test_allocation_is_rounded_up_to_whole_clusters(self, tmp_path: Path, windows_adapter):
        target = tmp_path / "setup.exe"
        target.write_bytes(os.urandom(5000))
        assert_that(windows_adapter.file_allocation(target).allocated_bytes).is_equal_to(
            5000 + -5000 % self._cluster_bytes(tmp_path)
        )

    @pytest.mark.parametrize("length", [100, 512])
    def test_file_stored_inside_its_mft_record_holds_no_clusters(self, tmp_path: Path, windows_adapter, length: int):
        target = tmp_path / "tiny.cfg"
        target.write_bytes(os.urandom(length))
        assert_that(windows_adapter.file_allocation(target).allocated_bytes).is_equal_to(0)

    def test_cluster_size_is_looked_up_once_per_volume(self, tmp_path: Path, windows_adapter, monkeypatch):
        from steamcleaner.platform import windows  # winreg and kernel32 are Windows-only

        lookups: list[str] = []
        query_cluster_bytes = windows._query_cluster_bytes

        def record_and_query(extended_path: str) -> int:
            lookups.append(extended_path)
            return query_cluster_bytes(extended_path)

        monkeypatch.setattr(windows, "_query_cluster_bytes", record_and_query)
        for name in ("first.bin", "second.bin"):
            (tmp_path / name).write_bytes(os.urandom(5000))
            windows_adapter.file_allocation(tmp_path / name)
        assert_that(lookups).is_length(1)

    def test_hard_links_share_an_identity_and_report_two_links(self, tmp_path: Path, windows_adapter):
        original = tmp_path / "setup.exe"
        original.write_bytes(os.urandom(5000))
        link = tmp_path / "setup_copy.exe"
        os.link(original, link)
        first = windows_adapter.file_allocation(original)
        second = windows_adapter.file_allocation(link)
        assert_that(first.link_count).is_equal_to(2)
        assert_that(second).is_equal_to(first)

    def test_unrelated_files_have_different_identities(self, tmp_path: Path, windows_adapter):
        first = tmp_path / "first.bin"
        second = tmp_path / "second.bin"
        first.write_bytes(b"\x00" * 10)
        second.write_bytes(b"\x00" * 10)
        assert_that(windows_adapter.file_allocation(first).file_id).is_not_equal_to(
            windows_adapter.file_allocation(second).file_id
        )
        assert_that(windows_adapter.file_allocation(first).link_count).is_equal_to(1)

    def test_compressed_file_holds_less_than_its_length(self, tmp_path: Path, windows_adapter):
        target = tmp_path / "log.txt"
        target.write_bytes(b"steamcleaner compressible line\n" * 40_000)
        compact = subprocess.run(["compact", "/c", str(target)], capture_output=True, check=False)
        if compact.returncode != 0:
            pytest.skip("the volume does not support NTFS compression")
        allocated = windows_adapter.file_allocation(target).allocated_bytes
        assert_that(allocated).is_between(1, target.stat().st_size // 2)
        assert_that(allocated).is_equal_to(self._compressed_bytes(target))

    def test_wof_compressed_file_is_measured_alone_and_through_its_directory(self, tmp_path: Path, windows_adapter):
        cache = tmp_path / "cache"
        cache.mkdir()
        target = cache / "shader.bin"
        target.write_bytes(b"steamcleaner compressible line\n" * 40_000)
        compact = subprocess.run(["compact", "/c", "/exe:xpress4k", str(target)], capture_output=True, check=False)
        if compact.returncode != 0:
            pytest.skip("the volume does not support WOF compression")
        allocated = self._compressed_bytes(target)
        assert_that(allocated).is_between(1, target.stat().st_size // 2)
        assert_that(windows_adapter.file_allocation(target).allocated_bytes).is_equal_to(allocated)
        assert_that(disk_usage(target, windows_adapter)).is_equal_to(allocated)
        assert_that(disk_usage(cache, windows_adapter)).is_equal_to(allocated)

    def test_structures_match_the_layout_windows_fills_in(self):
        from steamcleaner.platform import windows  # winreg and kernel32 are Windows-only

        assert_that(ctypes.sizeof(windows._FileStandardInfo)).is_equal_to(24)
        assert_that(windows._FileStandardInfo.NumberOfLinks.offset).is_equal_to(16)
        assert_that(ctypes.sizeof(windows._ByHandleFileInformation)).is_equal_to(52)
        assert_that(windows._ByHandleFileInformation.dwVolumeSerialNumber.offset).is_equal_to(28)
        assert_that(windows._ByHandleFileInformation.nFileIndexHigh.offset).is_equal_to(44)

    @pytest.mark.parametrize("failing_call", ["GetFileInformationByHandleEx", "GetFileInformationByHandle"])
    def test_handle_is_closed_when_a_query_fails(self, tmp_path: Path, windows_adapter, monkeypatch, failing_call: str):
        from steamcleaner.platform import windows  # winreg and kernel32 are Windows-only

        target = tmp_path / "setup.exe"
        target.write_bytes(b"\x00" * 10)
        closed_handles: list[int] = []
        close_handle = windows._KERNEL32.CloseHandle

        def record_and_close(handle: int) -> int:
            closed_handles.append(handle)
            return close_handle(handle)

        monkeypatch.setattr(windows._KERNEL32, failing_call, lambda *_arguments: 0)
        monkeypatch.setattr(windows._KERNEL32, "CloseHandle", record_and_close)

        assert_that(windows_adapter.file_allocation).raises(OSError).when_called_with(target)
        assert_that(closed_handles).is_length(1)

    def test_path_longer_than_260_characters_is_measured(self, tmp_path: Path, windows_adapter):
        deep = tmp_path.joinpath(*[f"very_long_directory_name_{index:02d}" for index in range(12)])
        extended = "\\\\?\\" + str(deep)
        os.makedirs(extended)
        with open(extended + "\\file.bin", "wb") as handle:
            handle.write(b"\x00" * 5000)
        assert_that(len(str(deep))).is_greater_than(260)
        assert_that(windows_adapter.file_allocation(deep / "file.bin").allocated_bytes).is_greater_than(5000)

    @pytest.mark.parametrize(
        ("path", "extended"),
        [
            pytest.param(r"C:\Games\Half-Life\setup.exe", r"\\?\C:\Games\Half-Life\setup.exe", id="drive"),
            pytest.param(r"\\server\share\setup.exe", r"\\?\UNC\server\share\setup.exe", id="unc"),
            pytest.param(r"\\?\C:\Games\setup.exe", r"\\?\C:\Games\setup.exe", id="already-extended"),
        ],
    )
    def test_path_is_passed_to_windows_in_its_extended_form(self, path: str, extended: str):
        from steamcleaner.platform.windows import _extended_path  # winreg and kernel32 are Windows-only

        assert_that(_extended_path(Path(path))).is_equal_to(extended)

    def test_missing_file_raises_os_error(self, tmp_path: Path, windows_adapter):
        assert_that(windows_adapter.file_allocation).raises(FileNotFoundError).when_called_with(tmp_path / "gone.bin")
