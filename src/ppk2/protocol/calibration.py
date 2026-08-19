"""Per-sample current calibration.

[`current_micro_amps`][] is the pure mathematical conversion from one
raw 14-bit ADC count + range index + per-device coefficients + the
present VDD setpoint to a calibrated current value in microamperes.

It does NOT apply the post-range-change rolling-average / spike filter —
that lives in the stream parser, which is stateful. This function is
stateless and matches Nordic's ``getAdcResult`` term-for-term.

Regression-tested against a sample word from a real PPK2 with its
captured coefficients: ``0x015c0097`` → ``5.302145379685201`` µA.
"""

from ppk2.protocol.metadata import CalibrationCoefficients

# PPK2 firmware quirk: converts ADC counts into volts-per-ohm-equivalent
# before per-range scaling. 1.8 is the ADC reference; 163840 = 2^14 * 10
# is the firmware's chosen scaling base (post-decimation 14-bit ADC,
# then *10 internal headroom).
_ADC_MULT: float = 1.8 / 163_840.0


def current_micro_amps(
    adc_14: int,
    range_idx: int,
    vdd_mv: int,
    coeffs: CalibrationCoefficients,
) -> float:
    """Convert one calibrated ADC reading into microamps.

    The ADC *4 rescale (line 1 of the formula: ``adc_16 = adc_14 * 4``)
    is done internally. Callers pass the raw 14-bit value directly from
    [`ppk2.protocol.sample.RawSample`][]'s ``adc_14`` field.

    Args:
        adc_14: 14-bit ADC value (0..=16_383).
        range_idx: 3-bit auto-range index. Must be 0..=4; stream parser
            callers drop out-of-range samples via
            [`ppk2.protocol.sample.RawSample.range_valid`][].
        vdd_mv: Present VDD setpoint in millivolts (whatever was last sent
            via ``REGULATOR_SET``). Used by the VDD-dependent term —
            required even in ammeter mode.
        coeffs: Per-device calibration from [`parse_metadata`][].

    Returns:
        Calibrated current in microamperes.

    Raises:
        IndexError: If ``range_idx`` is outside the 0..=4 range of
            calibration arrays.
    """
    r = range_idx

    # Step 1 — rescale to 16-bit, subtract per-range offset, scale to volts-per-ohm.
    adc_16 = float(adc_14) * 4.0
    result_without_gain = (adc_16 - coeffs.o[r]) * (_ADC_MULT / coeffs.r[r])

    # Step 2 — quadratic gain correction + VDD-dependent linear term.
    rwg = result_without_gain
    vdd_volts = float(vdd_mv) / 1000.0
    corrected = coeffs.ug[r] * (
        rwg * (coeffs.gs[r] * rwg + coeffs.gi[r]) + coeffs.s[r] * vdd_volts + coeffs.i[r]
    )

    # Step 3 — amperes → microamperes.
    return corrected * 1e6
