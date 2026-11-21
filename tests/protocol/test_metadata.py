"""Metadata parser tests, including parity with the captured reference fixture."""

import json
import math

import pytest

from ppk2 import (
    CalibrationCoefficients,
    InvalidValue,
    MissingEnd,
    MissingField,
    parse_metadata,
)
from tests.protocol.fixtures import METADATA_PARSED_JSON, METADATA_RAW

_HAS_FIXTURE = METADATA_RAW.exists() and METADATA_PARSED_JSON.exists()


def _load_fixture() -> tuple[bytes, CalibrationCoefficients]:
    """The raw calibration text, and what Nordic's parser read from it."""
    raw = METADATA_RAW.read_bytes()
    ref = json.loads(METADATA_PARSED_JSON.read_text())
    coeffs = CalibrationCoefficients(
        calibrated=bool(ref["calibrated"]),
        r=tuple(ref["R"]),
        gs=tuple(ref["GS"]),
        gi=tuple(ref["GI"]),
        o=tuple(ref["O"]),
        s=tuple(ref["S"]),
        i=tuple(ref["I"]),
        ug=tuple(ref["UG"]),
        vdd_mv=ref["vdd"],
        mode=ref["mode"],
        hw=ref["hw"],
        ia=ref["ia"],
    )
    return raw, coeffs


@pytest.mark.skipif(
    not _HAS_FIXTURE,
    reason="captured metadata fixture not present; expected in tests/fixtures/",
)
def test_parses_captured_fixture_into_documented_struct() -> None:
    raw, expected = _load_fixture()
    parsed = parse_metadata(raw)

    # Per-range arrays compared element-by-element so any drift is
    # reported in field-and-index form.
    assert parsed.calibrated == expected.calibrated
    for name in ("r", "gs", "gi", "o", "s", "i", "ug"):
        got = getattr(parsed, name)
        want = getattr(expected, name)
        for idx, (g, w) in enumerate(zip(got, want, strict=True)):
            assert math.isclose(g, w, rel_tol=0, abs_tol=0), f"{name.upper()}[{idx}]: {g} != {w}"
    assert parsed.hw == expected.hw
    assert parsed.ia == expected.ia
    assert parsed.vdd_mv == expected.vdd_mv == 3300
    assert parsed.mode == expected.mode == 1


@pytest.mark.skipif(not _HAS_FIXTURE, reason="captured metadata fixture not present")
def test_parses_when_buffer_arrives_in_one_byte_chunks() -> None:
    """The parser is chunked-read-aware: caller accumulates, parser sees one blob."""
    raw = METADATA_RAW.read_bytes()
    # Simulate the accumulation a real caller does.
    accumulated = b""
    for byte in raw:
        accumulated += bytes((byte,))
        if accumulated.endswith(b"END\n") or accumulated.endswith(b"END"):
            break
    parsed = parse_metadata(accumulated)
    assert parsed.hw > 0
    assert parsed.ia > 0
    # 5 ranges, all finite, all non-zero GI (basic sanity).
    for gi in parsed.gi:
        assert gi != 0.0


def test_missing_end_terminator_raises_missing_end() -> None:
    buf = b"Calibrated: 0\nHW: 100\n"  # no END
    with pytest.raises(MissingEnd):
        parse_metadata(buf)


def test_missing_required_field_raises_missing_field() -> None:
    buf = b"Calibrated: 0\nHW: 100\nEND\n"  # no IA, no per-range
    with pytest.raises(MissingField) as exc:
        parse_metadata(buf)
    assert "R[0]" in str(exc.value) or "IA" in str(exc.value)


def test_invalid_calibrated_value_raises_invalid_value() -> None:
    buf = b"Calibrated: maybe\nHW: 100\nIA: 1\nEND\n"
    with pytest.raises(InvalidValue) as exc:
        parse_metadata(buf)
    assert exc.value.field == "Calibrated"


def _full_block_lines(*scalars: str) -> list[str]:
    """A complete coefficient block plus the given scalar lines."""
    lines = list(scalars)
    for prefix in ("R", "GS", "GI", "O", "S", "I", "UG"):
        for idx in range(5):
            lines.append(f"{prefix}{idx}: 1.0")
    return lines


def test_samples_glued_in_front_of_the_response_are_skipped() -> None:
    """The end of a stream that was not read out can precede the response.

    Measured on a PPK2: 900 to 964 bytes of samples, then ``Calibrated``
    with no newline in between. The parse starts at the first key.
    """
    lines = _full_block_lines("Calibrated: 1", "HW: 7", "IA: 3", "VDD: 3300", "mode: 1")
    block = "\n".join([*lines, "END", ""]).encode()
    samples = b"".join(bytes([0x20, 0x00, (4 * i) & 0xFF, 0x00]) for i in range(225))

    parsed = parse_metadata(samples + block)

    assert parsed == parse_metadata(block)
    assert parsed.hw == 7


def test_stray_bytes_and_a_newline_in_front_of_the_response_are_skipped() -> None:
    lines = _full_block_lines("Calibrated: 1", "HW: 7", "IA: 3", "VDD: 3300", "mode: 1")
    block = "\n".join([*lines, "END", ""]).encode()
    residue = bytes([0xFF, 0xFE, 0xFD, 0x81, 0x00, 0x13]) + b"\n"

    parsed = parse_metadata(residue + block)

    assert parsed.hw == 7
    assert parsed.vdd_mv == 3300


def test_unknown_keys_are_tolerated_for_forward_compat() -> None:
    """Build a synthetic full block + an unknown key; parser should not fail."""
    lines = [
        "Calibrated: 1",
        "HW: 12345",
        "IA: 67",
        "VDD: 1800",
        "mode: 2",
        "VERSION_OUT: 1.2.3",  # unknown: forward-compat skip
        "UNKNOWN_FUTURE_FIELD: 42",
    ]
    for prefix in ("R", "GS", "GI", "O", "S", "I", "UG"):
        for idx in range(5):
            lines.append(f"{prefix}{idx}: 1.0")
    # 6-range future-firmware emission: must be silently ignored.
    lines.append("R5: 99.99")
    buf = "\n".join([*lines, "END", ""]).encode()
    parsed = parse_metadata(buf)
    assert parsed.calibrated is True
    assert parsed.hw == 12345
    assert parsed.vdd_mv == 1800
    assert parsed.mode == 2


def test_missing_vdd_defaults_to_3300() -> None:
    """VDD is runtime state, not calibration: omitted key defaults, not fails."""
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1", "mode: 1")
    buf = "\n".join([*lines, "END", ""]).encode()
    parsed = parse_metadata(buf)
    assert parsed.vdd_mv == 3300


def test_missing_mode_defaults_to_ampere_meter() -> None:
    """mode is runtime state: omitted key defaults to 1 (Ampere meter, passive)."""
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1", "VDD: 3300")
    buf = "\n".join([*lines, "END", ""]).encode()
    parsed = parse_metadata(buf)
    assert parsed.mode == 1


def test_missing_both_vdd_and_mode_still_parses() -> None:
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1")
    buf = "\n".join([*lines, "END", ""]).encode()
    parsed = parse_metadata(buf)
    assert parsed.vdd_mv == 3300
    assert parsed.mode == 1


def test_present_but_garbage_vdd_still_raises_invalid_value() -> None:
    """Leniency covers ABSENT keys only: a present-but-broken value stays fatal."""
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1", "VDD: banana", "mode: 1")
    buf = "\n".join([*lines, "END", ""]).encode()
    with pytest.raises(InvalidValue) as exc:
        parse_metadata(buf)
    assert exc.value.field == "VDD"


def test_invalid_mode_value_raises_invalid_value() -> None:
    """Wire byte is 1 (Ampere meter) or 2 (Source meter), as in Nordic's app."""
    lines = [
        "Calibrated: 1",
        "HW: 1",
        "IA: 1",
        "VDD: 3300",
        "mode: 7",  # firmware misbehaves or wire corruption
    ]
    for prefix in ("R", "GS", "GI", "O", "S", "I", "UG"):
        for idx in range(5):
            lines.append(f"{prefix}{idx}: 1.0")
    buf = "\n".join([*lines, "END", ""]).encode()
    with pytest.raises(InvalidValue) as exc:
        parse_metadata(buf)
    assert exc.value.field == "mode"


def test_required_field_array_index_appears_in_missing_field_message() -> None:
    """Drop one per-range field and check the error mentions it precisely."""
    lines = [
        "Calibrated: 1",
        "HW: 1",
        "IA: 1",
        "VDD: 3300",
        "mode: 1",
    ]
    for prefix in ("R", "GS", "GI", "O", "S", "I", "UG"):
        for idx in range(5):
            if prefix == "S" and idx == 3:
                continue  # drop S[3]
            lines.append(f"{prefix}{idx}: 1.0")
    buf = "\n".join([*lines, "END", ""]).encode()
    with pytest.raises(MissingField) as exc:
        parse_metadata(buf)
    assert exc.value.field == "S[3]"


def test_blank_slot_takes_the_apps_default() -> None:
    """The firmware prints ``-nan`` for a slot left blank; Nordic's app assumes a default.

    Nominal resistance for ``R``, 1 for the gains, 0 for the offsets.
    """
    for blank in ("-nan", "nan"):
        lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1")
        lines += [
            f"R4: {blank}",
            f"GS2: {blank}",
            f"O1: {blank}",
            f"UG0: {blank}",
        ]  # later line wins
        buf = "\n".join([*lines, "END", ""]).encode()

        parsed = parse_metadata(buf)

        assert parsed.r == (1.0, 1.0, 1.0, 1.0, 0.043)
        assert parsed.gs[2] == 1.0
        assert parsed.o[1] == 0.0
        assert parsed.ug[0] == 1.0


def test_infinite_coefficient_raises_invalid_value() -> None:
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1", "GS2: inf")
    buf = "\n".join([*lines, "END", ""]).encode()
    with pytest.raises(InvalidValue) as exc:
        parse_metadata(buf)
    assert exc.value.field == "GS[2]"


def test_zero_coefficient_is_kept_not_defaulted() -> None:
    """A literal 0 coefficient is kept, where Nordic's app takes its default.

    The app treats an exact 0 like a blank slot; we keep the value the
    device reported: a recorded divergence. (GS0 ≈ 1e-19 on real
    units, one calibration bit away from exactly 0.)
    """
    lines = _full_block_lines("Calibrated: 1", "HW: 1", "IA: 1")
    lines.append("GS0: 0")  # later line wins over the builder's 1.0
    buf = "\n".join([*lines, "END", ""]).encode()
    parsed = parse_metadata(buf)
    assert parsed.gs[0] == 0.0
