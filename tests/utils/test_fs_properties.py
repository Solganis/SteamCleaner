"""Property-based tests for format_size.

The unit-selection and one-decimal rounding logic is only sampled at six points by
the example tests; these checks hold across the whole input range.
"""

from assertpy2 import assert_that
from hypothesis import given
from hypothesis import strategies as st

from steamcleaner.utils.fs import format_size

_UNIT_MULTIPLIER = {"KB": 1024**1, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_ALL_SUFFIXES = (" B", " KB", " MB", " GB", " TB")


class TestFormatSizeProperties:
    @given(st.integers(min_value=0, max_value=2**70))
    def test_output_ends_with_known_unit(self, size_bytes):
        formatted = format_size(size_bytes)
        assert_that(any(formatted.endswith(suffix) for suffix in _ALL_SUFFIXES)).is_true()

    @given(st.integers(min_value=0, max_value=1023))
    def test_below_one_kib_is_exact_byte_count(self, size_bytes):
        assert_that(format_size(size_bytes)).is_equal_to(f"{size_bytes} B")

    @given(st.integers(min_value=1024, max_value=2**70))
    def test_roundtrip_magnitude_within_rounding_tolerance(self, size_bytes):
        number_text, unit = format_size(size_bytes).rsplit(" ", 1)
        multiplier = _UNIT_MULTIPLIER[unit]
        reconstructed = float(number_text) * multiplier
        # The scaled value is shown with one decimal, so the absolute error of the
        # reconstructed byte count is bounded by half a displayed step (0.05 * multiplier).
        assert_that(abs(reconstructed - size_bytes)).is_less_than_or_equal_to(0.05 * multiplier + 1)
