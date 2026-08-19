"""Sample-frame bit extraction.

Each PPK2 sample is a 4-byte little-endian word::

    bits 0-13   ADC      (14-bit raw count; *4 to rescale to 16-bit
                          before the calibration formula)
    bits 14-16  RANGE    (auto-range selector, 0..=4; 5..=7 = corrupt parse)
    bit  17     reserved (read as 0; don't assert on it)
    bits 18-23  COUNTER  (6-bit mod-64 monotonic; the stream parser's
                          resync hook)
    bits 24-31  LOGIC    (D0..D7; bit 0 = D0)
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawSample:
    """One sample frame after bit extraction.

    No calibration applied; no validation applied. See [`range_valid`][]
    for the ``range <= 4`` check that stream alignment relies on.

    Attributes:
        adc_14: Raw 14-bit ADC reading (0..=16_383). Multiply by 4 before
            feeding the calibration formula.
        range: Auto-range index. Healthy firmware emits 0..=4; anything
            ≥ 5 is a misaligned-parse signal.
        counter: 6-bit per-sample counter (0..=63), increments mod 64.
        logic: Digital input pins D0..D7 packed into one byte (bit 0 = D0).
    """

    adc_14: int
    range: int
    counter: int
    logic: int

    def range_valid(self) -> bool:
        """``True`` iff the range index is in the documented 0..=4 window."""
        return self.range <= 4

    def pin(self, pin: int) -> bool:
        """``True`` iff digital pin ``pin`` (0..=7) was high in this sample.

        ``pin`` is masked to 3 bits; out-of-range values wrap.
        """
        return ((self.logic >> (pin & 0x7)) & 1) != 0


def decode_sample(raw: int) -> RawSample:
    """Decode a single 4-byte little-endian sample word into its fields.

    Pure mechanical extraction — no validation, no calibration. The stream
    parser is responsible for dropping out-of-range samples; the
    calibration layer is responsible for the *4 rescale and the per-range
    formula.

    Args:
        raw: 32-bit unsigned integer (a ``u32`` worth of sample word).

    Returns:
        [`RawSample`][] with the four fields populated.
    """
    return RawSample(
        adc_14=raw & 0x3FFF,
        range=(raw >> 14) & 0x07,
        counter=(raw >> 18) & 0x3F,
        logic=(raw >> 24) & 0xFF,
    )


def decode_sample_bytes(buf: bytes) -> RawSample:
    """Decode from a 4-byte little-endian buffer (convenience wrapper).

    Args:
        buf: Exactly 4 bytes.

    Returns:
        Same [`RawSample`][] as [`decode_sample`][] reached via the
        ``int`` path.

    Raises:
        ValueError: If ``buf`` is not exactly 4 bytes long.
    """
    if len(buf) != 4:
        raise ValueError(f"expected 4 bytes, got {len(buf)}")
    return decode_sample(int.from_bytes(buf, "little"))
