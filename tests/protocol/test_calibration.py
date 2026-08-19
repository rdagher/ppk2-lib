"""Calibration formula tests, including a worked example from the captured fixture."""

import math

import pytest

from ppk2 import CalibrationCoefficients, current_micro_amps, parse_metadata
from tests.protocol.fixtures import METADATA_RAW

_HAS_FIXTURE = METADATA_RAW.exists()


@pytest.mark.skipif(not _HAS_FIXTURE, reason="captured metadata fixture not present")
def test_worked_example_matches_fixture_to_f64_precision() -> None:
    """Worked example computed from the captured fixture coefficients.

    From ``tests/fixtures/metadata.raw``: adc_14=151, range=0,
    vdd=3300 -> 5.302145379685201 µA. Expected value computed
    independently in IEEE-754 f64; CPython float (same width) must
    match bit-for-bit.
    """
    coeffs = parse_metadata(METADATA_RAW.read_bytes())
    computed = current_micro_amps(151, 0, 3300, coeffs)
    expected = 5.302145379685201
    assert math.isclose(computed, expected, rel_tol=0, abs_tol=0), (
        f"worked example: {computed!r} vs {expected!r}"
    )


def test_identity_coefficients_reduce_to_adc_mult() -> None:
    """R=1, O=0, GS=0, GI=1, S=0, I=0, UG=1 -> current = adc_16 * ADC_MULT * 1e6."""
    coeffs = CalibrationCoefficients(
        calibrated=True,
        r=(1.0, 1.0, 1.0, 1.0, 1.0),
        gs=(0.0, 0.0, 0.0, 0.0, 0.0),
        gi=(1.0, 1.0, 1.0, 1.0, 1.0),
        o=(0.0, 0.0, 0.0, 0.0, 0.0),
        s=(0.0, 0.0, 0.0, 0.0, 0.0),
        i=(0.0, 0.0, 0.0, 0.0, 0.0),
        ug=(1.0, 1.0, 1.0, 1.0, 1.0),
        vdd_mv=3300,
        mode=1,
        hw=0,
        ia=0,
    )
    adc_14 = 100
    computed = current_micro_amps(adc_14, 0, 3300, coeffs)
    expected = (float(adc_14) * 4.0) * (1.8 / 163_840.0) * 1e6
    assert math.isclose(computed, expected, rel_tol=0, abs_tol=0)
