"""Property-based tests for the VDF parser.

Example-based tests in test_vdf.py pin down specific shapes; these check the two
algebraic properties that hold for *any* input: a quoted round-trip is the
identity, and the parser only ever fails with VdfParseError.
"""

from assertpy2 import assert_that
from hypothesis import given, settings
from hypothesis import strategies as st

from steamcleaner.utils.vdf import VdfDict, VdfParseError, parse_vdf


def _escape_vdf_string(raw: str) -> str:
    """Escape backslash and double quote so parse_vdf reconstructs the original string.

    Order matters: backslashes are doubled first, otherwise the escape we add for a
    quote would itself be re-escaped. Whitespace and braces are left raw because the
    parser treats them literally inside quotes.
    """
    return raw.replace("\\", "\\\\").replace('"', '\\"')


def _serialize_vdf(data: VdfDict, indent: int = 0) -> str:
    """Render a nested dict back into VDF text, the inverse of parse_vdf for quoted tokens."""
    padding = "\t" * indent
    lines: list[str] = []
    for key, value in data.items():
        quoted_key = f'"{_escape_vdf_string(key)}"'
        if isinstance(value, dict):
            lines.append(f"{padding}{quoted_key}")
            lines.append(f"{padding}{{")
            nested = _serialize_vdf(value, indent + 1)
            if nested:
                lines.append(nested)
            lines.append(f"{padding}}}")
        else:
            lines.append(f'{padding}{quoted_key} "{_escape_vdf_string(value)}"')
    return "\n".join(lines)


# Bias the alphabet toward the characters that exercise the parser's branches
# (quotes, backslashes, braces, comment slashes, whitespace) while still covering
# Cyrillic and CJK ranges per the project's unicode-path requirement.
_structural_chars = st.sampled_from('"\\{}/ \t\n')
_unicode_chars = st.characters(min_codepoint=32, max_codepoint=0x2FFF, exclude_categories=("Cs",))

_vdf_string = st.text(alphabet=st.one_of(_structural_chars, _unicode_chars), max_size=8)
_vdf_key = st.text(alphabet=st.one_of(_structural_chars, _unicode_chars), min_size=1, max_size=8)

_vdf_dict = st.dictionaries(
    keys=_vdf_key,
    values=st.recursive(
        _vdf_string,
        lambda children: st.dictionaries(keys=_vdf_key, values=children, max_size=4),
        max_leaves=12,
    ),
    max_size=5,
)


class TestVdfRoundTrip:
    @given(_vdf_dict)
    @settings(deadline=None)  # recursive serialize/parse can exceed the default 200ms on slow CI
    def test_serialize_then_parse_is_identity(self, original):
        assert_that(parse_vdf(_serialize_vdf(original))).is_equal_to(original)


# Cap the length so accidental deep "{" nesting stays well under the recursion limit.
_arbitrary_text = st.text(
    alphabet=st.one_of(
        _structural_chars,
        st.characters(min_codepoint=32, max_codepoint=0x024F, exclude_categories=("Cs",)),
    ),
    max_size=80,
)


class TestVdfParserRobustness:
    @given(_arbitrary_text)
    @settings(deadline=None)
    def test_never_raises_outside_vdf_parse_error(self, raw_text):
        try:
            result = parse_vdf(raw_text)
        except VdfParseError:
            return  # the only failure mode the parser is allowed to expose
        assert_that(result).is_instance_of(dict)
