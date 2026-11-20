"""Per-sample current calibration.

``current_micro_amps`` turns one raw ADC count into microamperes, given
the range, the per-device coefficients, and the present supply voltage.
It is stateless and computes the same formula as Nordic's ``getAdcResult``;
the spike filter that follows a range change lives in the stream
parser.

Regression-tested against a sample word from a real PPK2 with its
captured coefficients: ``0x015c0097`` gives ``5.302145379685201`` µA.
"""

from ppk2.protocol.metadata import CalibrationCoefficients

# The firmware's ADC scaling: a 1.8 V reference over 2^14 * 10 (the
# 14-bit count, with *10 of internal headroom).
_ADC_MULT: float = 1.8 / 163_840.0


def current_micro_amps(
    adc_14: int,
    range_idx: int,
    vdd_mv: int,
    coeffs: CalibrationCoefficients,
) -> float:
    """Convert one raw ADC reading into microamperes.

    Args:
        adc_14: 14-bit ADC value, straight from ``RawSample.adc_14``
            (the *4 rescale happens here).
        range_idx: Range index, 0-4.
        vdd_mv: Present supply voltage in millivolts (the last
            ``REGULATOR_SET``). Needed in Ampere meter mode too.
        coeffs: Per-device calibration from ``parse_metadata``.

    Raises:
        IndexError: If ``range_idx`` is above 4.
    """
    r = range_idx

    # Measured voltage over the range's resistance: the current before correction, in amperes.
    counts = float(adc_14) * 4.0 - coeffs.o[r]
    raw_amps = counts * (_ADC_MULT / coeffs.r[r])

    # The per-range correction: a quadratic in the raw current, plus a
    # term that follows the supply voltage.
    vdd_volts = float(vdd_mv) / 1000.0
    amps = coeffs.ug[r] * (
        raw_amps * (coeffs.gs[r] * raw_amps + coeffs.gi[r]) + coeffs.s[r] * vdd_volts + coeffs.i[r]
    )
    return amps * 1e6
