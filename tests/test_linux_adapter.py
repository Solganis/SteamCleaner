from pathlib import Path

from steamcleaner.platform.linux import LinuxAdapter


class TestLinuxAdapter:
    def test_registry_returns_none(self):
        adapter = LinuxAdapter()
        assert adapter.read_registry_str("HKLM", r"SOFTWARE\Valve\Steam", "InstallPath") is None

    def test_home(self):
        adapter = LinuxAdapter()
        assert adapter.home() == Path.home()

    def test_appdata_local_default(self, monkeypatch):
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        adapter = LinuxAdapter()
        assert adapter.appdata_local() == Path.home() / ".local" / "share"

    def test_appdata_local_xdg(self, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/data")
        adapter = LinuxAdapter()
        assert adapter.appdata_local() == Path("/custom/data")

    def test_appdata_roaming_default(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        adapter = LinuxAdapter()
        assert adapter.appdata_roaming() == Path.home() / ".config"

    def test_appdata_roaming_xdg(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/config")
        adapter = LinuxAdapter()
        assert adapter.appdata_roaming() == Path("/custom/config")
