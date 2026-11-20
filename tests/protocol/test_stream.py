"""Stream parser tests.

Includes a parity check against a captured byte stream and its parse
by Nordic's own code (see tests/fixtures/README.md). The reference CSV
carries currents at 3-decimal precision; the comparison allows for
that rounding.
"""

import math

import pytest

from ppk2 import (
    DEFAULT_SPIKE_FILTER_ALPHA,
    DEFAULT_SPIKE_FILTER_ALPHA5,
    DEFAULT_SPIKE_FILTER_SAMPLES,
    MAX_BUFFERED_CORRUPTED,
    CalibrationCoefficients,
    Sample,
    SpikeFilter,
    StreamParser,
    parse_metadata,
)
from tests.protocol.fixtures import METADATA_RAW, PARSED_CSV, STREAM_BIN

_VDD_MV = 3300
_TOLERANCE_UA = 0.001  # the reference is rounded to 3 decimals


def test_stream_parser_matches_nordic_on_a_captured_stream() -> None:
    """Same raw bytes, parsed here and by the code of Nordic's app: same currents and logic.

    The stream is a DUT power-on: all five measurement ranges, nine range changes,
    so the calibration of each range and the spike filter are compared.
    """
    rows = [line.split(",") for line in PARSED_CSV.read_text().splitlines()[1:]]
    expected_ua = [float(row[1]) for row in rows]
    expected_logic = [int(row[2]) for row in rows]

    parser = StreamParser(parse_metadata(METADATA_RAW.read_bytes()), _VDD_MV)
    produced: list[Sample] = []
    parser.push_bytes(STREAM_BIN.read_bytes(), produced.append)

    assert len(produced) == len(expected_ua)
    worst, index = max(
        (abs(sample.current_micro_amps - ua), i)
        for i, (sample, ua) in enumerate(zip(produced, expected_ua, strict=True))
    )
    assert worst <= _TOLERANCE_UA, (
        f"sample {index}: ours {produced[index].current_micro_amps:.6f} µA, "
        f"reference {expected_ua[index]:.6f} µA"
    )
    assert [sample.logic for sample in produced] == expected_logic


def test_stream_parser_stashes_sub_4_byte_input_until_complete() -> None:
    """Sub-word input is stashed in the remainder buffer; emits on completion.

    Matches Nordic's ``remainder: Buffer`` behavior at
    ``serialDevice.ts:299``: a chunk that ends mid-word must not
    drop the trailing 1-3 bytes; they're consumed when the next chunk
    arrives.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    word = _make_word(adc=42, range_idx=0, counter=0, logic=0x5A)
    payload = word.to_bytes(4, "little")

    # First push: 3 of 4 bytes -> 0 emits, 3 bytes stashed.
    parser.push_bytes(payload[:3], emitted.append)
    assert emitted == []

    # Second push: the missing 4th byte -> 1 emit, remainder cleared.
    parser.push_bytes(payload[3:4], emitted.append)
    assert len(emitted) == 1
    assert emitted[0].logic == 0x5A


def test_stream_parser_handles_misaligned_chunks_across_calls() -> None:
    """Three 5-byte chunks must yield three samples + 3 stashed bytes consumed.

    5 + 5 + 5 = 15 bytes. With 4-byte words and a remainder buffer:
    - After call 1 (5 bytes): emit 1 (bytes 0..3), stash 1 (byte 4).
    - After call 2 (5 bytes, prepended to 1 stashed -> 6): emit 1
      (bytes 0..3 of combined), stash 2.
    - After call 3 (5 bytes, prepended to 2 stashed -> 7): emit 1
      (bytes 0..3 of combined), stash 3.
    Final: 3 emits, 3 bytes still in the remainder buffer.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    payload = b"".join(
        _make_word(adc=100 + i, range_idx=0, counter=i, logic=i).to_bytes(4, "little")
        for i in range(4)  # 16 bytes total
    )

    for offset in (0, 5, 10):
        parser.push_bytes(payload[offset : offset + 5], emitted.append)

    assert len(emitted) == 3


def test_stream_parser_drops_range_out_of_spec_samples() -> None:
    """A word with range = 5..=7 must not produce a Sample."""
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)

    # Word with range bits = 5 (out of spec). Construct: bits 14-16 = 0b101 = 5.
    bad_word = 0b101 << 14
    bad_bytes = bad_word.to_bytes(4, "little")

    emitted: list[Sample] = []
    parser.push_bytes(bad_bytes, emitted.append)
    assert emitted == []


def test_clean_stream_emits_every_sample_in_order() -> None:
    """Monotonically-increasing counters: every input -> exactly one output, in order."""
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)

    emitted: list[Sample] = []
    n = 20
    payload = b"".join(
        _make_word(adc=10 + i, range_idx=0, counter=i & 0x3F, logic=i & 0xFF).to_bytes(4, "little")
        for i in range(n)
    )
    parser.push_bytes(payload, emitted.append)

    assert len(emitted) == n
    # Logic bytes were i & 0xFF: a strict-ordering tell-tale that
    # samples weren't reordered.
    for i, s in enumerate(emitted):
        assert s.logic == i & 0xFF


def test_brief_mismatch_drained_on_matched_recovery() -> None:
    """A short noisy interval that resolves drains the buffered samples into the timeline.

    With expected counter advancing past a small gap, the mismatched
    samples sit in the corruption buffer; when a counter matches the
    advanced-expected value, the buffer drains in FIFO order, then
    the current sample emits: every input surfaces exactly once.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)

    emitted: list[Sample] = []

    # Seed with counter=0 -> expected becomes 1, emit s0.
    seed = _make_word(adc=100, range_idx=0, counter=0, logic=0xA0)
    parser.push_bytes(seed.to_bytes(4, "little"), emitted.append)
    assert [s.logic for s in emitted] == [0xA0]

    # Mismatch: send counter=3 (skip 1, 2). Expected (1) != 3, buffer < 5, push and advance.
    # buffered=[s_3], expected = 2
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=3, logic=0xA3).to_bytes(4, "little"),
        emitted.append,
    )
    # No new emit yet: s_3 sits in the buffer.
    assert [s.logic for s in emitted] == [0xA0]

    # Match at expected=2: drain buffer + emit current. Order: s_3 (drained), s_2 (current).
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=2, logic=0xA2).to_bytes(4, "little"),
        emitted.append,
    )
    assert [s.logic for s in emitted] == [0xA0, 0xA3, 0xA2]


def test_buffer_overflow_emits_nan_placeholders_and_resyncs() -> None:
    """After MAX_BUFFERED_CORRUPTED mismatches without recovery, declare data loss.

    NaN placeholders are emitted for the (counter - expected) gap, then
    the held samples, then the trigger sample. Subsequent matched
    samples continue normally.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    # Seed with counter=0 -> expected = 1, emit s0.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=0, logic=0).to_bytes(4, "little"), emitted.append
    )
    emitted.clear()

    # Send MAX_BUFFERED_CORRUPTED mismatched samples: all buffered.
    # Counters chosen to be far from expected and from each other so
    # they look like real noise rather than a stuck counter.
    mismatch_counters = [10, 20, 30, 40, 50]  # exactly 5 = MAX_BUFFERED_CORRUPTED
    for c in mismatch_counters:
        parser.push_bytes(
            _make_word(adc=100, range_idx=0, counter=c, logic=0xFF).to_bytes(4, "little"),
            emitted.append,
        )
    # Nothing emitted yet: buffer at threshold but not over.
    assert emitted == []

    # 6th mismatch triggers data-loss path. Trigger with counter=10
    # (any non-matching value). Expected at this point: 1 + 5 = 6.
    # gap = (10 - 6) & 0x3F = 4 -> 4 NaN placeholders, the 5 held
    # samples, then the trigger sample.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=10, logic=0x55).to_bytes(4, "little"),
        emitted.append,
    )
    assert len(emitted) == 10  # 4 NaN + 5 held + 1 trigger
    for nan_sample in emitted[:4]:
        assert math.isnan(nan_sample.current_micro_amps)
        assert nan_sample.logic == 0  # placeholders carry no logic data
    assert [s.logic for s in emitted[4:9]] == [0xFF] * 5
    trigger = emitted[9]
    assert not math.isnan(trigger.current_micro_amps)
    assert trigger.logic == 0x55

    # After the data-loss path expected is reset to
    # (trigger.counter + 1) = 11. A subsequent in-sync sample emits
    # normally.
    emitted.clear()
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=11, logic=0x42).to_bytes(4, "little"),
        emitted.append,
    )
    assert len(emitted) == 1
    assert emitted[0].logic == 0x42


@pytest.mark.parametrize("lost", [1, 10, 40, 63])
def test_lost_samples_keep_the_timeline_exact(lost: int) -> None:
    """``lost`` samples vanish on the wire and the stream goes on.

    Every sample period must get exactly one slot: a placeholder for
    each lost sample, and every sample that did arrive, in order.
    """
    parser = StreamParser(_identity_coeffs(), _VDD_MV)
    emitted: list[Sample] = []
    before, after = 10, 20
    sent = [*range(before), *range(before + lost, before + lost + after)]
    for seq in sent:
        word = _make_word(adc=100, range_idx=0, counter=seq & 0x3F, logic=seq & 0xFF)
        parser.push_bytes(word.to_bytes(4, "little"), emitted.append)

    assert len(emitted) == before + lost + after
    arrived = [s.logic for s in emitted if not math.isnan(s.current_micro_amps)]
    assert arrived == [seq & 0xFF for seq in sent]
    assert all(math.isnan(s.current_micro_amps) for s in emitted[before : before + lost])
    assert parser.dataloss_total == lost


def test_max_buffered_corrupted_constant_matches_nordic_threshold() -> None:
    """Pinning the constant value: Nordic's serialDevice.ts:268 fires on length > 4."""
    assert MAX_BUFFERED_CORRUPTED == 5


def test_dataloss_total_counts_nan_placeholders_only() -> None:
    """dataloss_total counts the NaN placeholders, not the held samples.

    Like Nordic's dataLossCounter (serialDevice.ts), it grows by the
    (counter - expectedCounter) gap only.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    # Seed.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=0, logic=0).to_bytes(4, "little"), emitted.append
    )
    assert parser.dataloss_total == 0

    # 5 mismatched samples to fill the buffer.
    for c in (10, 20, 30, 40, 50):
        parser.push_bytes(
            _make_word(adc=100, range_idx=0, counter=c, logic=0).to_bytes(4, "little"),
            emitted.append,
        )
    assert parser.dataloss_total == 0  # nothing dropped yet, just buffered

    # Trigger sample (counter=10, expected=6 after 5 mismatch advances).
    # gap = (10 - 6) & 0x3F = 4 -> dataloss_total should grow by 4.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=10, logic=0).to_bytes(4, "little"), emitted.append
    )
    assert parser.dataloss_total == 4


def test_genuine_loss_keeps_the_samples_that_arrived_after_the_gap() -> None:
    """Genuine forward loss: placeholders for the lost samples, then the real ones.

    When samples are lost in transit the counter jumps forward and
    stays consecutive, so the next 5 arrivals are held back and the 6th
    declares the loss. The held samples are real and came after the
    gap: they surface after the placeholders, each in its own slot.
    Nordic's app shows them too (it emits them on arrival).
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    # In-sync prelude: counters 0..3 emit as they arrive.
    for c in range(4):
        parser.push_bytes(
            _make_word(adc=100, range_idx=0, counter=c, logic=c).to_bytes(4, "little"),
            emitted.append,
        )
    assert [s.logic for s in emitted] == [0, 1, 2, 3]

    # Genuine loss: counters 4..23 never arrive. The stream resumes at
    # 24 and stays consecutive: every arrival is REAL data.
    for c in (24, 25, 26, 27, 28):
        parser.push_bytes(
            _make_word(adc=100, range_idx=0, counter=c, logic=c).to_bytes(4, "little"),
            emitted.append,
        )
    # All five held (expected advanced 4 -> 9), nothing emitted yet.
    assert [s.logic for s in emitted] == [0, 1, 2, 3]

    # 6th consecutive mismatch (counter=29, expected=9) declares the
    # loss: gap = (29 - 9) & 0x3F = 20 placeholders for 4..23, then the
    # held 24..28, then 29. One slot per sample period, 0 through 29.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=29, logic=29).to_bytes(4, "little"),
        emitted.append,
    )
    assert len(emitted) == 30
    assert all(math.isnan(s.current_micro_amps) for s in emitted[4:24])
    assert [s.logic for s in emitted[24:]] == [24, 25, 26, 27, 28, 29]
    assert not any(math.isnan(s.current_micro_amps) for s in emitted[24:])
    assert parser.dataloss_total == 20

    # Resynced: the next consecutive sample emits normally.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=30, logic=30).to_bytes(4, "little"),
        emitted.append,
    )
    assert emitted[-1].logic == 30


def test_dataloss_gap_uses_true_mod64_arithmetic_across_counter_wrap() -> None:
    """The placeholder count is the TRUE mod-64 gap, exercised across the 63->0 wrap.

    Pins the gap off-by-one fix: shipped Nordic (serialDevice.ts:269-271
    @ 63ae4b7) computes ``(counter - expected + 63) & 63``, one short
    of the true distance. With expected=2 and trigger counter=1 the
    true mod-64 gap is 63; the shipped arithmetic would emit 62. The
    wrap also proves the expected-counter advances correctly through
    63 -> 0 while mismatches are being buffered.
    """
    coeffs = _identity_coeffs()
    parser = StreamParser(coeffs, _VDD_MV)
    emitted: list[Sample] = []

    # Seed near the top of the counter range: expected becomes 61.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=60, logic=0x60).to_bytes(4, "little"),
        emitted.append,
    )
    assert len(emitted) == 1

    # 5 mismatches fill the buffer; expected advances 61 -> 62 -> 63 -> 0 -> 1 -> 2.
    for c in (0, 10, 20, 30, 40):
        parser.push_bytes(
            _make_word(adc=100, range_idx=0, counter=c, logic=0xFF).to_bytes(4, "little"),
            emitted.append,
        )
    assert len(emitted) == 1  # all buffered

    # Trigger: counter=1 vs expected=2 -> true gap (1 - 2) & 0x3F = 63.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=1, logic=0x55).to_bytes(4, "little"),
        emitted.append,
    )
    placeholders = emitted[1:-6]
    assert len(placeholders) == 63  # shipped Nordic's `+ 63` would give 62
    assert all(math.isnan(s.current_micro_amps) for s in placeholders)
    assert all(s.logic == 0 for s in placeholders)
    assert [s.logic for s in emitted[-6:-1]] == [0xFF] * 5  # the held samples
    assert emitted[-1].logic == 0x55
    assert parser.dataloss_total == 63

    # Resynced to (trigger + 1) = 2: an in-sync follow-up emits.
    parser.push_bytes(
        _make_word(adc=100, range_idx=0, counter=2, logic=0x42).to_bytes(4, "little"),
        emitted.append,
    )
    assert emitted[-1].logic == 0x42


def test_spike_filter_defaults_match_module_level_constants() -> None:
    """Default-constructed SpikeFilter pins the defaults of Nordic's app."""
    sf = SpikeFilter()
    assert sf.samples == DEFAULT_SPIKE_FILTER_SAMPLES == 3
    assert sf.alpha == DEFAULT_SPIKE_FILTER_ALPHA == 0.18
    assert sf.alpha5 == DEFAULT_SPIKE_FILTER_ALPHA5 == 0.06


def test_spike_filter_rejects_negative_samples() -> None:
    with pytest.raises(ValueError, match="samples"):
        SpikeFilter(samples=-1)


def test_spike_filter_rejects_alpha_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match="alpha"):
        SpikeFilter(alpha=1.5)
    with pytest.raises(ValueError, match="alpha"):
        SpikeFilter(alpha=-0.01)


def test_spike_filter_rejects_alpha5_outside_unit_interval() -> None:
    with pytest.raises(ValueError, match="alpha5"):
        SpikeFilter(alpha5=2.0)


def test_explicit_default_filter_matches_implicit_default_byte_for_byte() -> None:
    """``SpikeFilter()`` keyword is byte-equivalent to omitting the kwarg.

    The constants -> dataclass refactor must not change the smoothed
    output for callers who don't pass a filter, otherwise the parity
    fixture would silently flip. Drive both with the same input and
    require exact equality.
    """
    coeffs = _identity_coeffs()
    payload = b"".join(
        _make_word(adc=10 + i, range_idx=i % 5, counter=i & 0x3F, logic=i & 0xFF).to_bytes(
            4, "little"
        )
        for i in range(40)
    )

    default_implicit: list[Sample] = []
    StreamParser(coeffs, _VDD_MV).push_bytes(payload, default_implicit.append)

    default_explicit: list[Sample] = []
    StreamParser(coeffs, _VDD_MV, SpikeFilter()).push_bytes(payload, default_explicit.append)

    assert len(default_implicit) == len(default_explicit)
    for a, b in zip(default_implicit, default_explicit, strict=True):
        # Bit-exact: SpikeFilter() default path must hit the same EMA arithmetic.
        assert a.current_micro_amps == b.current_micro_amps
        assert a.logic == b.logic


def test_custom_alpha_changes_smoothed_output_inside_window() -> None:
    """A different ``alpha`` produces a different rolling_avg inside the smoothing window.

    Construction: one range 0 -> 1 -> 0 transition pair primes the
    post-transition window with ``samples`` length remaining; the
    subsequent same-range samples at varying ADC values evolve the EMA
    differently under different alphas. We compare bit-exact equality
    on the in-window samples.
    """
    coeffs = _identity_coeffs()
    # Sample 0: range 0, adc 100 (primes prev_range, EMA seed).
    # Sample 1: range 1, adc 100 (transition #1: after_spike = samples).
    # Sample 2: range 0, adc 100 (transition #2: after_spike = samples again).
    # Samples 3..6: range 0, varying adc -> in-window, EMA-dependent output.
    descriptors: list[tuple[int, int]] = [
        (100, 0),
        (100, 1),
        (100, 0),
        (200, 0),
        (16_000, 0),
        (300, 0),
        (16_000, 0),
    ]
    payload = b"".join(
        _make_word(adc=adc, range_idx=r, counter=i & 0x3F, logic=0).to_bytes(4, "little")
        for i, (adc, r) in enumerate(descriptors)
    )

    # Bump samples so the window covers the varying-adc tail of the payload.
    default_out: list[Sample] = []
    StreamParser(coeffs, _VDD_MV, SpikeFilter(samples=10)).push_bytes(payload, default_out.append)

    heavy_out: list[Sample] = []
    StreamParser(coeffs, _VDD_MV, SpikeFilter(samples=10, alpha=0.01)).push_bytes(
        payload, heavy_out.append
    )

    assert len(default_out) == len(heavy_out) == len(descriptors)
    # At least one sample must differ; if everything matches, the knob
    # isn't reaching the EMA arithmetic.
    diffs = [
        a.current_micro_amps != b.current_micro_amps
        for a, b in zip(default_out, heavy_out, strict=True)
    ]
    assert any(diffs), "alpha override didn't reach the EMA: knob is dead"


def test_custom_samples_shortens_smoothing_window() -> None:
    """``samples=0`` collapses the post-transition window to a single in-window sample.

    Compared against the default ``samples=3``, the tail of a varying-ADC
    stream after one range transition must diverge: the wider window
    keeps the EMA output engaged for more samples.
    """
    coeffs = _identity_coeffs()
    descriptors: list[tuple[int, int]] = [
        (100, 0),
        (100, 1),
        (100, 0),
        (10_000, 0),
        (10_000, 0),
        (10_000, 0),
        (10_000, 0),
        (10_000, 0),
    ]
    payload = b"".join(
        _make_word(adc=adc, range_idx=r, counter=i & 0x3F, logic=0).to_bytes(4, "little")
        for i, (adc, r) in enumerate(descriptors)
    )

    wide_out: list[Sample] = []
    StreamParser(coeffs, _VDD_MV, SpikeFilter(samples=5)).push_bytes(payload, wide_out.append)

    narrow_out: list[Sample] = []
    StreamParser(coeffs, _VDD_MV, SpikeFilter(samples=0)).push_bytes(payload, narrow_out.append)

    diffs = [
        a.current_micro_amps != b.current_micro_amps
        for a, b in zip(wide_out, narrow_out, strict=True)
    ]
    assert any(diffs), "samples override didn't change in-window length"


# ─── Helpers ────────────────────────────────────────────────────────────


def _identity_coeffs() -> CalibrationCoefficients:
    """Build a coefficients block that makes the calibration formula trivial."""
    return CalibrationCoefficients(
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


def _make_word(adc: int, range_idx: int, counter: int, logic: int) -> int:
    """Pack the four fields into one 32-bit sample word."""
    return (adc & 0x3FFF) | ((range_idx & 0x07) << 14) | ((counter & 0x3F) << 18) | (logic << 24)
