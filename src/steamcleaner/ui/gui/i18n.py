import json
from pathlib import Path

from steamcleaner.utils.config import get_value, save_value

_LOCALES_DIR = Path(__file__).parent / "locales"

_cache: dict[str, dict[str, str]] = {}


def _load_translations(lang: str) -> dict[str, str]:
    locale_file = _LOCALES_DIR / f"{lang}.json"
    try:
        text = locale_file.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}
    except OSError, json.JSONDecodeError:
        pass
    return {}


def _get_translations(lang: str) -> dict[str, str]:
    if lang not in _cache:
        _cache[lang] = _load_translations(lang)
    return _cache[lang]


def available_languages() -> list[str]:
    return [path.stem for path in sorted(_LOCALES_DIR.glob("*.json"))]


LANGUAGES = {"en": "English", "ru": "Русский", "zh": "中文", "es": "Español", "pt-BR": "Português (Brasil)"}

_current_lang = "en"


def init_lang() -> None:
    global _current_lang
    saved = get_value("ui", "language")
    _current_lang = saved if saved in LANGUAGES else "en"


def set_lang(lang: str) -> None:
    global _current_lang
    if lang in LANGUAGES:
        _current_lang = lang
        save_value("ui", "language", lang)


def get_lang() -> str:
    return _current_lang


def t(key: str, **kwargs: str | int) -> str:
    text = _get_translations(_current_lang).get(key)
    if text is None:
        text = _get_translations("en").get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def t_category(category_value: str) -> str:
    return t(f"cat_{category_value}")
