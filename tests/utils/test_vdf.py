from pathlib import Path

import pytest
from assertpy2 import assert_that

from steamcleaner.utils.vdf import VdfParseError, load_vdf, parse_vdf


class TestParseVdfSimple:
    def test_empty_string(self):
        assert_that(parse_vdf("")).is_equal_to({})

    def test_whitespace_only(self):
        assert_that(parse_vdf("   \n\t  ")).is_equal_to({})

    def test_single_key_value(self):
        assert_that(parse_vdf('"key" "value"')).is_equal_to({"key": "value"})

    def test_multiple_key_values(self):
        result = parse_vdf('"a" "1"\n"b" "2"')
        assert_that(result).is_equal_to({"a": "1", "b": "2"})

    def test_tab_separated(self):
        result = parse_vdf('"path"\t\t"C:\\\\Games"')
        assert_that(result).is_equal_to({"path": "C:\\Games"})


class TestParseVdfNested:
    def test_single_nested_block(self):
        text = '"root"\n{\n  "child" "value"\n}'
        result = parse_vdf(text)
        assert_that(result).is_equal_to({"root": {"child": "value"}})

    def test_deeply_nested(self):
        text = '"a"\n{\n  "b"\n  {\n    "c" "deep"\n  }\n}'
        result = parse_vdf(text)
        assert_that(result).is_equal_to({"a": {"b": {"c": "deep"}}})

    def test_empty_block(self):
        result = parse_vdf('"empty"\n{\n}')
        assert_that(result).is_equal_to({"empty": {}})

    def test_sibling_blocks(self):
        text = '"first"\n{\n  "key" "1"\n}\n"second"\n{\n  "key" "2"\n}'
        result = parse_vdf(text)
        assert_that(result).is_equal_to({"first": {"key": "1"}, "second": {"key": "2"}})

    def test_mixed_values_and_blocks(self):
        text = '"flat" "yes"\n"nested"\n{\n  "inner" "data"\n}'
        result = parse_vdf(text)
        assert_that(result).is_equal_to({"flat": "yes", "nested": {"inner": "data"}})


class TestParseVdfComments:
    def test_line_comment_skipped(self):
        text = '// this is a comment\n"key" "value"'
        assert_that(parse_vdf(text)).is_equal_to({"key": "value"})

    def test_inline_comment_after_value(self):
        text = '"key" "value"\n// comment after\n"key2" "value2"'
        result = parse_vdf(text)
        assert_that(result).is_equal_to({"key": "value", "key2": "value2"})

    def test_comment_inside_block(self):
        text = '"root"\n{\n  // inner comment\n  "key" "value"\n}'
        assert_that(parse_vdf(text)).is_equal_to({"root": {"key": "value"}})

    def test_only_comments(self):
        assert_that(parse_vdf("// nothing here\n// also nothing")).is_equal_to({})


class TestParseVdfEscapeSequences:
    def test_escaped_quote(self):
        result = parse_vdf(r'"key" "say \"hello\""')
        assert_that(result).is_equal_to({"key": 'say "hello"'})

    def test_escaped_backslash(self):
        result = parse_vdf(r'"path" "C:\\Games\\Steam"')
        assert_that(result).is_equal_to({"path": "C:\\Games\\Steam"})

    def test_escaped_newline(self):
        result = parse_vdf(r'"msg" "line1\nline2"')
        assert_that(result).is_equal_to({"msg": "line1\nline2"})

    def test_escaped_tab(self):
        result = parse_vdf(r'"msg" "col1\tcol2"')
        assert_that(result).is_equal_to({"msg": "col1\tcol2"})

    def test_unknown_escape_preserved(self):
        result = parse_vdf(r'"key" "test\xvalue"')
        assert_that(result).is_equal_to({"key": "test\\xvalue"})


class TestParseVdfUnquoted:
    def test_unquoted_keys_and_values(self):
        result = parse_vdf("key value")
        assert_that(result).is_equal_to({"key": "value"})

    def test_unquoted_key_quoted_value(self):
        result = parse_vdf('key "quoted value"')
        assert_that(result).is_equal_to({"key": "quoted value"})

    def test_unquoted_key_with_block(self):
        result = parse_vdf("root\n{\n  key val\n}")
        assert_that(result).is_equal_to({"root": {"key": "val"}})


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
        assert_that(folders).is_instance_of(dict)
        assert_that(folders).is_length(2)

        folder_0 = folders["0"]
        assert_that(folder_0).is_instance_of(dict)
        assert_that(folder_0["path"]).is_equal_to("C:\\Program Files (x86)\\Steam")

        folder_1 = folders["1"]
        assert_that(folder_1).is_instance_of(dict)
        assert_that(folder_1["path"]).is_equal_to("D:\\SteamLibrary")

        apps = folder_0["apps"]
        assert_that(apps).is_instance_of(dict)
        assert_that(apps["730"]).is_equal_to("987654321")

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
        assert_that(steam).is_instance_of(dict)
        assert_that(steam["BaseInstallFolder_1"]).is_equal_to("D:\\SteamLibrary")
        assert_that(steam["BaseInstallFolder_2"]).is_equal_to("E:\\Games\\Steam")

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
        assert_that(state).is_instance_of(dict)
        assert_that(state["appid"]).is_equal_to("730")
        assert_that(state["name"]).is_equal_to("Counter-Strike 2")
        assert_that(state["installdir"]).is_equal_to("Counter-Strike Global Offensive")


class TestLoadVdf:
    def test_loads_valid_file(self, tmp_path: Path):
        vdf_file = tmp_path / "test.vdf"
        vdf_file.write_text('"key" "value"', encoding="utf-8")
        result = load_vdf(vdf_file)
        assert_that(result).is_equal_to({"key": "value"})

    def test_missing_file_returns_empty(self, tmp_path: Path):
        result = load_vdf(tmp_path / "nonexistent.vdf")
        assert_that(result).is_equal_to({})

    def test_malformed_file_returns_empty(self, tmp_path: Path):
        vdf_file = tmp_path / "bad.vdf"
        vdf_file.write_text('"unclosed', encoding="utf-8")
        result = load_vdf(vdf_file)
        assert_that(result).is_equal_to({})

    def test_empty_file(self, tmp_path: Path):
        vdf_file = tmp_path / "empty.vdf"
        vdf_file.write_text("", encoding="utf-8")
        result = load_vdf(vdf_file)
        assert_that(result).is_equal_to({})

    def test_malformed_unquoted_triggers_error(self, tmp_path: Path):
        vdf_file = tmp_path / "bad.vdf"
        vdf_file.write_text("{", encoding="utf-8")
        result = load_vdf(vdf_file)
        assert_that(result).is_equal_to({})
