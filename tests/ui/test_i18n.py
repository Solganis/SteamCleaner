import json
from pathlib import Path

from assertpy2 import assert_that

from steamcleaner.ui.gui import i18n
from steamcleaner.ui.gui.i18n import LANGUAGES, t

LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "steamcleaner" / "ui" / "gui" / "locales"


# noinspection PyProtectedMemberAccess
class TestLocaleFiles:
    def test_all_languages_have_json_files(self):
        for lang_code in LANGUAGES:
            locale_file = LOCALES_DIR / f"{lang_code}.json"
            assert_that(str(locale_file)).described_as(f"Missing locale file for {lang_code}").is_file()

    def test_all_json_files_are_valid(self):
        for locale_file in LOCALES_DIR.glob("*.json"):
            text = locale_file.read_text(encoding="utf-8")
            data = json.loads(text)
            assert_that(data).described_as(f"{locale_file.name} root must be an object").is_instance_of(dict)
            for key, value in data.items():
                assert_that(key).described_as(f"{locale_file.name}: key {key!r} must be a string").is_instance_of(str)
                assert_that(value).described_as(
                    f"{locale_file.name}: value for {key!r} must be a string"
                ).is_instance_of(str)

    def test_all_languages_have_same_keys_as_english(self):
        english = i18n._load_translations("en")
        english_keys = set(english.keys())
        assert_that(english_keys).described_as("English translations must not be empty").is_not_empty()
        for lang_code in LANGUAGES:
            if lang_code == "en":
                continue
            translations = i18n._load_translations(lang_code)
            lang_keys = set(translations.keys())
            missing = english_keys - lang_keys
            extra = lang_keys - english_keys
            assert_that(missing).described_as(f"{lang_code} missing keys: {missing}").is_empty()
            assert_that(extra).described_as(f"{lang_code} has extra keys: {extra}").is_empty()


# noinspection PyProtectedMemberAccess
class TestTranslationFunction:
    def test_returns_english_by_default(self):
        result = t("ready")
        assert_that(result).is_instance_of(str)
        assert_that(result).is_not_empty()

    def test_format_parameters(self):
        result = t("found_items", count=5, size="10 MB")
        assert_that(result).contains("5")
        assert_that(result).contains("10 MB")

    def test_missing_key_returns_key_itself(self):
        result = t("nonexistent_key_12345")
        assert_that(result).is_equal_to("nonexistent_key_12345")

    def test_fallback_to_english(self):
        english = i18n._get_translations("en")
        assert_that(english).contains("ready")


# noinspection PyProtectedMemberAccess
class TestLoadTranslations:
    def test_load_english(self):
        translations = i18n._load_translations("en")
        assert_that(translations).contains("ready")
        assert_that(translations["ready"]).is_equal_to("Ready")

    def test_load_russian(self):
        translations = i18n._load_translations("ru")
        assert_that(translations).contains("ready")
        assert_that(translations["ready"]).is_equal_to("Готово")

    def test_load_nonexistent_returns_empty(self):
        translations = i18n._load_translations("xx-nonexistent")
        assert_that(translations).is_equal_to({})
