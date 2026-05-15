import json
from pathlib import Path

from steamcleaner.ui.gui import i18n
from steamcleaner.ui.gui.i18n import LANGUAGES, t

LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "steamcleaner" / "ui" / "gui" / "locales"


# noinspection PyProtectedMemberAccess
class TestLocaleFiles:
    def test_all_languages_have_json_files(self):
        for lang_code in LANGUAGES:
            locale_file = LOCALES_DIR / f"{lang_code}.json"
            assert locale_file.is_file(), f"Missing locale file for {lang_code}"

    def test_all_json_files_are_valid(self):
        for locale_file in LOCALES_DIR.glob("*.json"):
            text = locale_file.read_text(encoding="utf-8")
            data = json.loads(text)
            assert isinstance(data, dict), f"{locale_file.name} root must be an object"
            for key, value in data.items():
                assert isinstance(key, str), f"{locale_file.name}: key {key!r} must be a string"
                assert isinstance(value, str), f"{locale_file.name}: value for {key!r} must be a string"

    def test_all_languages_have_same_keys_as_english(self):
        english = i18n._load_translations("en")
        english_keys = set(english.keys())
        assert english_keys, "English translations must not be empty"
        for lang_code in LANGUAGES:
            if lang_code == "en":
                continue
            translations = i18n._load_translations(lang_code)
            lang_keys = set(translations.keys())
            missing = english_keys - lang_keys
            extra = lang_keys - english_keys
            assert not missing, f"{lang_code} missing keys: {missing}"
            assert not extra, f"{lang_code} has extra keys: {extra}"


# noinspection PyProtectedMemberAccess
class TestTranslationFunction:
    def test_returns_english_by_default(self):
        result = t("ready")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_parameters(self):
        result = t("found_items", count=5, size="10 MB")
        assert "5" in result
        assert "10 MB" in result

    def test_missing_key_returns_key_itself(self):
        result = t("nonexistent_key_12345")
        assert result == "nonexistent_key_12345"

    def test_fallback_to_english(self):
        english = i18n._get_translations("en")
        assert "ready" in english


# noinspection PyProtectedMemberAccess
class TestLoadTranslations:
    def test_load_english(self):
        translations = i18n._load_translations("en")
        assert "ready" in translations
        assert translations["ready"] == "Ready"

    def test_load_russian(self):
        translations = i18n._load_translations("ru")
        assert "ready" in translations
        assert translations["ready"] == "Готово"

    def test_load_nonexistent_returns_empty(self):
        translations = i18n._load_translations("xx-nonexistent")
        assert translations == {}
