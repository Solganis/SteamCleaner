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

    def test_list_registry_subkeys_returns_empty(self):
        adapter = LinuxAdapter()
        assert adapter.list_registry_subkeys("HKLM", r"SOFTWARE\Test") == []

    def test_programdata(self):
        adapter = LinuxAdapter()
        assert adapter.programdata() == Path("/var/lib")


class TestLinuxWinePrefixes:
    def test_empty_when_no_prefixes_exist(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        adapter = LinuxAdapter()
        assert adapter.wine_prefixes() == []

    def test_finds_default_wine_prefix(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        drive_c = tmp_path / ".wine" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_finds_proton_compatdata(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        compatdata = tmp_path / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        drive_c = compatdata / "12345" / "pfx" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_finds_flatpak_compatdata(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        flatpak = (
            tmp_path
            / ".var"
            / "app"
            / "com.valvesoftware.Steam"
            / ".local"
            / "share"
            / "Steam"
            / "steamapps"
            / "compatdata"
        )
        drive_c = flatpak / "67890" / "pfx" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_finds_bottles_native(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        bottles_root = tmp_path / ".local" / "share" / "bottles" / "bottles"
        drive_c = bottles_root / "my-bottle" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_finds_bottles_flatpak(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        bottles_root = tmp_path / ".var" / "app" / "com.usebottles.bottles" / "data" / "bottles" / "bottles"
        drive_c = bottles_root / "gaming" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_finds_lutris_runners(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        lutris = tmp_path / ".local" / "share" / "lutris" / "runners" / "wine"
        drive_c = lutris / "prefix1" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert drive_c in prefixes

    def test_no_duplicates(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        drive_c = tmp_path / ".wine" / "drive_c"
        drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert prefixes.count(drive_c) == 1

    def test_skips_dirs_without_drive_c(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        compatdata = tmp_path / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        (compatdata / "99999" / "pfx").mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert len(prefixes) == 0

    def test_multiple_sources_combined(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        wine_drive_c = tmp_path / ".wine" / "drive_c"
        wine_drive_c.mkdir(parents=True)
        compatdata = tmp_path / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
        proton_drive_c = compatdata / "11111" / "pfx" / "drive_c"
        proton_drive_c.mkdir(parents=True)
        bottles_root = tmp_path / ".local" / "share" / "bottles" / "bottles"
        bottle_drive_c = bottles_root / "gaming" / "drive_c"
        bottle_drive_c.mkdir(parents=True)
        adapter = LinuxAdapter()
        prefixes = adapter.wine_prefixes()
        assert wine_drive_c in prefixes
        assert proton_drive_c in prefixes
        assert bottle_drive_c in prefixes
        assert len(prefixes) == 3
