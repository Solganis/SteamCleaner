from pathlib import Path

import pytest

from steamcleaner.utils.vdf import VdfParseError, load_vdf, parse_vdf


class TestParseVdfSimple:
    def test_empty_string(self):
        assert parse_vdf("") == {}

    def test_whitespace_only(self):
        assert parse_vdf("   \n\t  ") == {}

    def test_single_key_value(self):
        assert parse_vdf('"key" "value"') == {"key": "value"}

    def test_multiple_key_values(self):
        result = parse_vdf('"a" "1"\n"b" "2"')
        assert result == {"a": "1", "b": "2"}

    def test_tab_separated(self):
        result = parse_vdf('"path"\t\t"C:\\\\Games"')
        assert result == {"path": "C:\\Games"}


class TestParseVdfNested:
    def test_single_nested_block(self):
        text = '"root"\n{\n  "child" "value"\n}'
        result = parse_vdf(text)
        assert result == {"root": {"child": "value"}}

    def test_deeply_nested(self):
        text = '"a"\n{\n  "b"\n  {\n    "c" "deep"\n  }\n}'
        result = parse_vdf(text)
        assert result == {"a": {"b": {"c": "deep"}}}

    def test_empty_block(self):
        result = parse_vdf('"empty"\n{\n}')
        assert result == {"empty": {}}

    def test_sibling_blocks(self):
        text = '"first"\n{\n  "key" "1"\n}\n"second"\n{\n  "key" "2"\n}'
        result = parse_vdf(text)
        assert result == {"first": {"key": "1"}, "second": {"key": "2"}}

    def test_mixed_values_and_blocks(self):
        text = '"flat" "yes"\n"nested"\n{\n  "inner" "data"\n}'
        result = parse_vdf(text)
        assert result == {"flat": "yes", "nested": {"inner": "data"}}


class TestParseVdfComments:
    def test_line_comment_skipped(self):
        text = '// this is a comment\n"key" "value"'
        assert parse_vdf(text) == {"key": "value"}

    def test_inline_comment_after_value(self):
        text = '"key" "value"\n// comment after\n"key2" "value2"'
        result = parse_vdf(text)
        assert result == {"key": "value", "key2": "value2"}

    def test_comment_inside_block(self):
        text = '"root"\n{\n  // inner comment\n  "key" "value"\n}'
        assert parse_vdf(text) == {"root": {"key": "value"}}

    def test_only_comments(self):
        assert parse_vdf("// nothing here\n// also nothing") == {}


class TestParseVdfEscapeSequences:
    def test_escaped_quote(self):
        result = parse_vdf(r'"key" "say \"hello\""')
        assert result == {"key": 'say "hello"'}

    def test_escaped_backslash(self):
        result = parse_vdf(r'"path" "C:\\Games\\Steam"')
        assert result == {"path": "C:\\Games\\Steam"}

    def test_escaped_newline(self):
        result = parse_vdf(r'"msg" "line1\nline2"')
        assert result == {"msg": "line1\nline2"}

    def test_escaped_tab(self):
        result = parse_vdf(r'"msg" "col1\tcol2"')
        assert result == {"msg": "col1\tcol2"}

    def test_unknown_escape_preserved(self):
        result = parse_vdf(r'"key" "test\xvalue"')
        assert result == {"key": "test\\xvalue"}


class TestParseVdfUnquoted:
    def test_unquoted_keys_and_values(self):
        result = parse_vdf("key value")
        assert result == {"key": "value"}

    def test_unquoted_key_quoted_value(self):
        result = parse_vdf('key "quoted value"')
        assert result == {"key": "quoted value"}

    def test_unquoted_key_with_block(self):
        result = parse_vdf("root\n{\n  key val\n}")
        assert result == {"root": {"key": "val"}}


class TestParseVdfErrors:
    def test_unterminated_string(self):
        with pytest.raises(VdfParseError, match="Unterminated"):
            parse_vdf('"unclosed')

    def test_unclosed_block(self):
        with pytest.raises(VdfParseError, match="Expected '}'"):
            parse_vdf('"root"\n{\n  "key" "value"')

    def test_unexpected_content_after_root(self):
        with pytest.raises(VdfParseError, match="Unexpected content"):
            parse_vdf('"key" "value"\n}')

    def test_escape_at_end_of_input(self):
        with pytest.raises(VdfParseError, match="Unexpected end"):
            parse_vdf('"key" "value\\')


class TestParseVdfRealisticSteam:
    def test_libraryfolders_vdf(self):
        text = """\
"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"
\t\t"label"\t\t""
\t\t"contentid"\t\t"1234567890"
\t\t"totalsize"\t\t"0"
\t\t"update_clean_bytes_tally"\t\t"0"
\t\t"time_last_update_corruption"\t\t"0"
\t\t"apps"
\t\t{
\t\t\t"228980"\t\t"12345678"
\t\t\t"730"\t\t"987654321"
\t\t}
\t}
\t"1"
\t{
\t\t"path"\t\t"D:\\\\SteamLibrary"
\t\t"label"\t\t""
\t\t"apps"
\t\t{
\t\t\t"570"\t\t"11111111"
\t\t}
\t}
}"""
        result = parse_vdf(text)
        folders = result["libraryfolders"]
        assert isinstance(folders, dict)
        assert len(folders) == 2

        folder_0 = folders["0"]
        assert isinstance(folder_0, dict)
        assert folder_0["path"] == "C:\\Program Files (x86)\\Steam"

        folder_1 = folders["1"]
        assert isinstance(folder_1, dict)
        assert folder_1["path"] == "D:\\SteamLibrary"

        apps = folder_0["apps"]
        assert isinstance(apps, dict)
        assert apps["730"] == "987654321"

    def test_config_vdf_with_base_install_folders(self):
        text = """\
"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"BaseInstallFolder_1"\t\t"D:\\\\SteamLibrary"
\t\t\t\t"BaseInstallFolder_2"\t\t"E:\\\\Games\\\\Steam"
\t\t\t}
\t\t}
\t}
}"""
        result = parse_vdf(text)
        steam = result["InstallConfigStore"]["Software"]["Valve"]["Steam"]
        assert isinstance(steam, dict)
        assert steam["BaseInstallFolder_1"] == "D:\\SteamLibrary"
        assert steam["BaseInstallFolder_2"] == "E:\\Games\\Steam"

    def test_appmanifest_acf(self):
        text = """\
"AppState"
{
\t"appid"\t\t"730"
\t"Universe"\t\t"1"
\t"name"\t\t"Counter-Strike 2"
\t"StateFlags"\t\t"4"
\t"installdir"\t\t"Counter-Strike Global Offensive"
}"""
        result = parse_vdf(text)
        state = result["AppState"]
        assert isinstance(state, dict)
        assert state["appid"] == "730"
        assert state["name"] == "Counter-Strike 2"
        assert state["installdir"] == "Counter-Strike Global Offensive"


class TestLoadVdf:
    def test_loads_valid_file(self, tmp_path: Path):
        vdf_file = tmp_path / "test.vdf"
        vdf_file.write_text('"key" "value"', encoding="utf-8")
        result = load_vdf(vdf_file)
        assert result == {"key": "value"}

    def test_missing_file_returns_empty(self, tmp_path: Path):
        result = load_vdf(tmp_path / "nonexistent.vdf")
        assert result == {}

    def test_malformed_file_returns_empty(self, tmp_path: Path):
        vdf_file = tmp_path / "bad.vdf"
        vdf_file.write_text('"unclosed', encoding="utf-8")
        result = load_vdf(vdf_file)
        assert result == {}

    def test_empty_file(self, tmp_path: Path):
        vdf_file = tmp_path / "empty.vdf"
        vdf_file.write_text("", encoding="utf-8")
        result = load_vdf(vdf_file)
        assert result == {}
