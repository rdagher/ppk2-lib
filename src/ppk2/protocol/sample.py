"""Sample-frame bit extraction.

Each PPK2 sample is a 4-byte little-endian word::

    bits 0-13   ADC      (14-bit raw count; *4 to rescale to 16-bit
                          before the calibration formula)
    bits 14-16  RANGE    (auto-range selector, 0-4; 5-7 = misaligned parse)
    bit  17     reserved (read as 0; don't assert on it)
    bits 18-23  COUNTER  (6-bit, mod 64; what the stream parser
                          resyncs on)
    bits 24-31  LOGIC    (D0..D7; bit 0 = D0)
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawSample:
    """One sample frame after bit extraction: no calibration, no validation.

    Attributes:
        adc_14: Raw 14-bit ADC reading (0-16383).
        range: Auto-range index. Healthy firmware emits 0-4; 5 and up
            means the parse is misaligned.
        counter: 6-bit per-sample counter, incrementing mod 64.
        logic: Digital inputs D0..D7 in one byte (bit 0 = D0).
    """

    adc_14: int
    range: int
    counter: int
    logic: int

    def range_valid(self) -> bool:
        """Whether the range index is one of the five real ranges."""
        return self.range <= 4

    def pin(self, pin: int) -> bool:
        """Whether digital input ``pin`` (0-7) was high; ``pin`` wraps modulo 8."""
        return ((self.logic >> (pin & 0x7)) & 1) != 0


def decode_sample(raw: int) -> RawSample:
    """Split a 32-bit sample word into its fields (no validation)."""
    return RawSample(
        adc_14=raw & 0x3FFF,
        range=(raw >> 14) & 0x07,
        counter=(raw >> 18) & 0x3F,
        logic=(raw >> 24) & 0xFF,
    )


def decode_sample_bytes(buf: bytes) -> RawSample:
    """Same as ``decode_sample``, from exactly 4 little-endian bytes.

    Raises:
        ValueError: If ``buf`` is not 4 bytes long.
    """
    if len(buf) != 4:
        raise ValueError(f"expected 4 bytes, got {len(buf)}")
    return decode_sample(int.from_bytes(buf, "little"))
