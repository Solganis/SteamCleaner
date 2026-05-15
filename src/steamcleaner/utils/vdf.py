import logging
from pathlib import Path

_logger = logging.getLogger(__name__)

VdfDict = dict[str, "str | VdfDict"]


class VdfParseError(ValueError):
    pass


class _VdfParser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._length = len(text)

    def parse(self) -> VdfDict:
        result = self._parse_pairs()
        self._skip_whitespace_and_comments()
        if self._pos < self._length:
            raise VdfParseError(f"Unexpected content at position {self._pos}")
        return result

    def _parse_pairs(self) -> VdfDict:
        result: VdfDict = {}
        while True:
            self._skip_whitespace_and_comments()
            if self._pos >= self._length:
                break
            if self._peek() == "}":
                break
            key = self._parse_string()
            self._skip_whitespace_and_comments()
            if self._pos < self._length and self._peek() == "{":
                self._advance()
                value: str | VdfDict = self._parse_pairs()
                self._skip_whitespace_and_comments()
                if self._pos >= self._length or self._peek() != "}":
                    raise VdfParseError(f"Expected '}}' at position {self._pos}")
                self._advance()
            else:
                value = self._parse_string()
            result[key] = value
        return result

    def _parse_string(self) -> str:
        self._skip_whitespace_and_comments()
        if self._pos >= self._length:
            raise VdfParseError("Unexpected end of input while expecting a string")
        if self._peek() == '"':
            return self._parse_quoted_string()
        return self._parse_unquoted_string()

    def _parse_quoted_string(self) -> str:
        self._advance()
        chars: list[str] = []
        while self._pos < self._length:
            char = self._text[self._pos]
            if char == "\\":
                self._advance()
                if self._pos >= self._length:
                    raise VdfParseError("Unexpected end of input in escape sequence")
                escaped = self._text[self._pos]
                match escaped:
                    case '"':
                        chars.append('"')
                    case "\\":
                        chars.append("\\")
                    case "n":
                        chars.append("\n")
                    case "t":
                        chars.append("\t")
                    case _:
                        chars.append("\\")
                        chars.append(escaped)
            elif char == '"':
                self._advance()
                return "".join(chars)
            else:
                chars.append(char)
            self._advance()
        raise VdfParseError("Unterminated quoted string")

    def _parse_unquoted_string(self) -> str:
        start = self._pos
        while self._pos < self._length:
            char = self._text[self._pos]
            if char in (" ", "\t", "\n", "\r", '"', "{", "}"):
                break
            self._advance()
        if self._pos == start:
            raise VdfParseError(f"Expected string at position {self._pos}")
        return self._text[start : self._pos]

    def _skip_whitespace_and_comments(self) -> None:
        while self._pos < self._length:
            char = self._text[self._pos]
            if char in (" ", "\t", "\n", "\r"):
                self._advance()
            elif self._pos + 1 < self._length and self._text[self._pos : self._pos + 2] == "//":
                while self._pos < self._length and self._text[self._pos] != "\n":
                    self._advance()
            else:
                break

    def _peek(self) -> str:
        return self._text[self._pos]

    def _advance(self) -> None:
        self._pos += 1


def parse_vdf(text: str) -> VdfDict:
    """Parse a Valve VDF (KeyValues1) string into a nested dict."""
    return _VdfParser(text).parse()


def load_vdf(path: Path) -> VdfDict:
    """Load and parse a VDF file. Returns empty dict on any read/parse failure."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return parse_vdf(text)
    except (OSError, VdfParseError) as exc:
        _logger.debug("Failed to load VDF from %s: %s", path, exc)
        return {}
