"""Stateful byte-stream parser — alignment + counter resync + EMA spike filter.

Feed it raw bytes from the serial port via [`StreamParser.push_bytes`][];
it calls the supplied callback once per emitted sample.

Two state machines run in series per input word:

1. **Counter resync** — drops range-out-of-spec samples; on counter
   mismatch, buffers the offending sample. A subsequent matched-counter
   sample drains the buffer back into the output (the buffered samples
   were real, just delivered behind a brief gap). Once
   ``MAX_BUFFERED_CORRUPTED`` samples accumulate without recovery,
   declares data loss: emits ``float('nan')`` placeholders for the gap,
   drops the buffered samples, and resyncs to the current counter.
   Clean-room, intent-corrected port of the Nordic GUI's
   ``handleRawDataSet`` (``pc-nrfconnect-ppk`` @ ``63ae4b7``,
   ``src/device/serialDevice.ts:246-296``; unchanged through
   v4.4.1) — verified against that primary source. See
   [`StreamParser`][] for the three shipped-code bugs the port
   deliberately corrects.
2. **EMA smoothing** — two exponential moving averages (one alpha for
   ranges 0-3, a slower one for range 4), with a rollback path for the
   first two post-range-change samples at range 4. Knobs exposed via
   [`SpikeFilter`][].
"""

from collections.abc import Callable
from dataclasses import dataclass
from math import nan
from struct import iter_unpack

from ppk2.protocol.calibration import current_micro_amps
from ppk2.protocol.metadata import CalibrationCoefficients
from ppk2.protocol.sample import decode_sample


@dataclass(frozen=True, slots=True)
class Sample:
    """One sample after counter validation + calibration + EMA smoothing.

    Attributes:
        current_micro_amps: Calibrated current in microamperes. NaN
            indicates a data-loss placeholder (counter sync was lost
            and could not be recovered within
            ``MAX_BUFFERED_CORRUPTED`` samples); ``logic`` is 0
            for placeholders.
        logic: Digital input pins D0..D7 at the moment this sample was
            taken (bit 0 = D0). Always 0 for NaN placeholder samples.
    """

    current_micro_amps: float
    logic: int


#: Max consecutive mismatched samples we'll hold in the corruption
#: buffer before declaring data loss and emitting NaN placeholders.
#: Matches the Nordic GUI's threshold — recovery is declared impossible
#: when the 6th mismatched sample arrives without a matched counter
#: in between (the shipped code checks ``corruptedSamples.length > 4``
#: BEFORE pushing, ``serialDevice.ts:268`` @ ``63ae4b7``, so the
#: data-loss branch fires with exactly 5 samples buffered).
MAX_BUFFERED_CORRUPTED = 5

#: Default EMA coefficient for ranges 0..=3. Matches Nordic GUI's
#: ``spikeFilter.alpha`` default.
DEFAULT_SPIKE_FILTER_ALPHA: float = 0.18

#: Default EMA coefficient for range 4 (the slow range). Matches Nordic
#: GUI's ``spikeFilter.alpha5`` default.
DEFAULT_SPIKE_FILTER_ALPHA5: float = 0.06

#: Default post-range-change smoothing window length, in samples.
#: Matches Nordic GUI's ``spikeFilter.samples`` default.
DEFAULT_SPIKE_FILTER_SAMPLES: int = 3


@dataclass(frozen=True, slots=True)
class SpikeFilter:
    """Tunable knobs for the post-range-change EMA spike filter.

    Mirrors the three settings Nordic exposes under "Advanced
    Configuration → Spike filter" in their GUI:

    - ``samples`` — how many samples after a range change participate
      in the smoothing window. Larger = more smoothing on transients,
      slower recovery from a genuine new operating point.
    - ``alpha`` — EMA coefficient for ranges 0..=3. The fast EMA.
    - ``alpha5`` — EMA coefficient for range 4 only. The slow EMA;
      range 4 is the lowest-resistance shunt (~0.056 Ω, the ~60 mA-1 A
      range), for which Nordic ships a deliberately smaller
      coefficient (heavier smoothing).

    Defaults reproduce the Nordic GUI behaviour byte-for-byte against
    our [`StreamParser`][] regression fixture.

    Attributes:
        samples: Post-range-change smoothing window length, in samples.
            Must be ``>= 0``.
        alpha: EMA coefficient for ranges 0..=3. Must lie in
            ``[0.0, 1.0]``.
        alpha5: EMA coefficient for range 4 (the slow range). Must lie
            in ``[0.0, 1.0]``.
    """

    samples: int = DEFAULT_SPIKE_FILTER_SAMPLES
    alpha: float = DEFAULT_SPIKE_FILTER_ALPHA
    alpha5: float = DEFAULT_SPIKE_FILTER_ALPHA5

    def __post_init__(self) -> None:
        """Validate the three knobs are in their expected ranges."""
        if self.samples < 0:
            raise ValueError(f"samples must be >= 0, got {self.samples}")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError(f"alpha must be in [0.0, 1.0], got {self.alpha}")
        if not 0.0 <= self.alpha5 <= 1.0:
            raise ValueError(f"alpha5 must be in [0.0, 1.0], got {self.alpha5}")


_COUNTER_MASK = 0x3F  # 6-bit counter, mod 64

# Placeholder emitted in the data-loss path. logic = 0 because we have
# no real signal to report for the gap.
_NAN_SAMPLE = Sample(current_micro_amps=nan, logic=0)


class StreamParser:
    """Stateful PPK2 byte-stream → [`ppk2.protocol.stream.Sample`][] parser.

    One instance per session. Keeps a small remainder buffer (≤ 3
    bytes) across [`push_bytes`][] calls so callers that hand in
    non-4-aligned chunks don't lose words.

    On macOS with the production 4096-byte reads, alignment is always
    preserved in practice — the kernel CDC layer consistently fills
    the buffer in 4-byte multiples. The remainder buffer is there as
    defence-in-depth for Linux/Windows pyserial implementations with
    different buffering, contended hosts where read timeouts can fire
    mid-frame, and test fixtures that feed sub-word chunks
    deliberately.

    **Provenance.** The per-word counter-resync state machine is a
    clean-room port of the Nordic GUI's ``handleRawDataSet``
    (``pc-nrfconnect-ppk`` @ ``63ae4b7``,
    ``src/device/serialDevice.ts:246-296``; unchanged through
    v4.4.1), verified against that primary source, with three
    deliberate intent-corrections where the shipped code contradicts
    its own stated intent:

    - **duplicate-emission fix** — no buffer-empty guard on the trailing emission
      (``serialDevice.ts:284-285``). Shipped code fires the sample
      callback for every word after the branch logic, despite the
      "Only fire the event, if the buffer data is valid" comment
      directly above it — a mismatched sample is emitted at arrival
      AND re-emitted when the buffer later drains, duplicating
      samples and inflating the timeline. Here a mismatched sample
      is buffered only; the drain is its single emission path.
    - **gap off-by-one fix** (``serialDevice.ts:269-271``).
      Shipped code sizes the data-loss gap as
      ``(counter - expected + 63) & 63``, one short of the true
      mod-64 distance. Here the gap is ``(counter - expected) & 63``,
      so placeholders cover the real number of missing slots.
    - **corrupt-range fix** — corrupt range clamped instead of dropped
      (``serialDevice.ts:248-251``). Shipped code clamps the 3-bit
      range field with ``Math.min(range, 5)``, so a corrupt word
      indexes one past the end of the 5-element calibration arrays
      (``undefined`` → NaN current) and its garbage counter still
      drives the resync state machine. Here a range > 4 word is
      dropped entirely, without touching counter state.
    """

    def __init__(
        self,
        coeffs: CalibrationCoefficients,
        vdd_mv: int,
        spike_filter: SpikeFilter | None = None,
    ) -> None:
        """Build a fresh parser.

        Args:
            coeffs: Calibration block from
                [`ppk2.protocol.parse_metadata`][].
            vdd_mv: Present ``REGULATOR_SET`` setpoint in millivolts.
            spike_filter: Tunable EMA spike-filter knobs. ``None`` uses
                Nordic GUI defaults — that path is byte-identical to the
                pre-knob behaviour against our regression fixture.
        """
        self._coeffs = coeffs
        self._vdd_mv = vdd_mv
        self._spike_filter = spike_filter if spike_filter is not None else SpikeFilter()
        # Cross-call alignment buffer. Always 0-3 bytes; consumed on
        # the next call's first complete word.
        self._remainder = bytearray()
        # Counter-resync state.
        self._expected_counter: int | None = None
        self._corruption_buffer: list[Sample] = []
        #: Cumulative count of NaN data-loss placeholder samples
        #: emitted across this parser's lifetime. Monotonically
        #: non-decreasing. Public for diagnostics — capture-loop
        #: callers can compare against a baseline at the start of
        #: each ``push_bytes`` iteration to detect new losses.
        self.dataloss_total: int = 0
        # EMA / spike-filter state.
        self._prev_range: int | None = None
        self._rolling_avg: float | None = None
        self._rolling_avg4: float | None = None
        self._consecutive_range_sample = 0
        self._after_spike = 0

    def push_bytes(self, buf: bytes, emit: Callable[[Sample], None]) -> None:
        """Feed bytes from a serial read; emit one ``Sample`` per valid word.

        Bytes that don't form a complete 4-byte word are stashed in an
        internal remainder buffer and consumed on the next call.

        Args:
            buf: Bytes from ``serial.read()`` (or a test fixture).
            emit: Callback invoked once per emitted sample. May fire
                zero times (range-invalid, or mismatched sample that
                got buffered, or sub-word input) or multiple times
                (drain-on-recovery, or data-loss path that emits NaN
                placeholders) per input word.
        """
        # Fast path: no leftover bytes from the previous call.
        # `struct.iter_unpack` is a C-implemented native-loop unpacker;
        # 4-byte little-endian unsigned int per word. Significantly
        # faster than slicing bytes and calling int.from_bytes in pure
        # Python for the high-rate path.
        if not self._remainder:
            whole = len(buf) - (len(buf) % 4)
            if whole > 0:
                for (raw,) in iter_unpack("<I", buf[:whole]):
                    self._consume_word(raw, emit)
            if whole < len(buf):
                self._remainder.extend(buf[whole:])
            return

        # Slow path: prepend the leftover to this call's bytes.
        self._remainder.extend(buf)
        combined = bytes(self._remainder)
        self._remainder.clear()
        whole = len(combined) - (len(combined) % 4)
        if whole > 0:
            for (raw,) in iter_unpack("<I", combined[:whole]):
                self._consume_word(raw, emit)
        if whole < len(combined):
            self._remainder.extend(combined[whole:])

    def _consume_word(self, raw: int, emit: Callable[[Sample], None]) -> None:
        """Process one decoded 4-byte word; emit zero, one, or many samples."""
        raw_sample = decode_sample(raw)

        # Defence 1 — range validation. range_idx must index our 5-slot
        # calibration arrays; out-of-spec range means we're parsing at
        # the wrong byte offset, drop and let the next word retry.
        # Corrupt-range fix: dropped without touching counter state
        # (shipped Nordic clamps the range and lets the garbage word in).
        if not raw_sample.range_valid():
            return
        counter = raw_sample.counter

        # Calibrate + spike-filter the input sample before any
        # counter-routing decision. The EMA state must advance per
        # input sample so buffered-then-drained samples keep their
        # at-input-time smoothed value. Mirrors Nordic's getAdcResult
        # being called at the top of handleRawDataSet, before the
        # corruption-buffer logic.
        raw_ua = current_micro_amps(
            raw_sample.adc_14,
            raw_sample.range,
            self._vdd_mv,
            self._coeffs,
        )
        smoothed_ua = self._apply_spike_filter(raw_sample.range, raw_ua)
        sample = Sample(current_micro_amps=smoothed_ua, logic=raw_sample.logic)

        # Branch 1 — first valid sample. Seed expected counter and emit.
        if self._expected_counter is None:
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            emit(sample)
            return

        # Branch 2 — in sync. Drain any pending mismatched samples
        # first (they were real, just delivered behind a brief gap),
        # then emit the current sample.
        if counter == self._expected_counter:
            if self._corruption_buffer:
                for buffered in self._corruption_buffer:
                    emit(buffered)
                self._corruption_buffer.clear()
            emit(sample)
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            return

        # Branch 3 — buffer full + still mismatched. Recovery is
        # declared impossible: emit NaN placeholders covering the gap
        # from where we expected to be to where this sample says we
        # are, then emit this sample, drop the buffered ones, and
        # resync to the current counter.
        if len(self._corruption_buffer) >= MAX_BUFFERED_CORRUPTED:
            # True mod-64 gap — the gap off-by-one fix (shipped Nordic's
            # `+ 63` under-counts the missing slots by one).
            gap = (counter - self._expected_counter) & _COUNTER_MASK
            for _ in range(gap):
                emit(_NAN_SAMPLE)
            self.dataloss_total += gap
            emit(sample)
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            self._corruption_buffer.clear()
            return

        # Branch 4 — mismatch with room in the buffer. Defer emission;
        # the sample will either be drained on a future matched-counter
        # sample (branch 2) or discarded when branch 3 fires.
        # Duplicate-emission fix: buffered ONLY — shipped Nordic also
        # emits it here, then re-emits it on drain (duplicates).
        self._corruption_buffer.append(sample)
        self._expected_counter = (self._expected_counter + 1) & _COUNTER_MASK

    def _apply_spike_filter(self, range_idx: int, raw_ua: float) -> float:
        """Two-stage EMA with a post-range-change smoothing window."""
        alpha = self._spike_filter.alpha
        alpha5 = self._spike_filter.alpha5
        samples = self._spike_filter.samples

        # Snapshot pre-update EMAs (needed for the range-4 rollback below).
        prev_rolling_avg = self._rolling_avg
        prev_rolling_avg4 = self._rolling_avg4

        # Update both EMAs from raw, every sample.
        self._rolling_avg = (
            raw_ua
            if self._rolling_avg is None
            else alpha * raw_ua + (1.0 - alpha) * self._rolling_avg
        )
        self._rolling_avg4 = (
            raw_ua
            if self._rolling_avg4 is None
            else alpha5 * raw_ua + (1.0 - alpha5) * self._rolling_avg4
        )

        # Seed prev_range on first sample.
        if self._prev_range is None:
            self._prev_range = range_idx

        same_range = self._prev_range == range_idx
        in_window = (not same_range) or self._after_spike > 0
        out = raw_ua

        if in_window:
            if same_range:
                self._consecutive_range_sample += 1
            else:
                # Range transition just happened — reset the window.
                self._consecutive_range_sample = 0
                self._after_spike = samples

            if range_idx == 4:
                if self._consecutive_range_sample < 2:
                    # First two post-transition samples at range 4:
                    # roll the EMAs back to their pre-update values so
                    # the slow EMA tracks the new range more cleanly.
                    self._rolling_avg = prev_rolling_avg
                    self._rolling_avg4 = prev_rolling_avg4
                assert self._rolling_avg4 is not None, "just-updated EMA must be set"
                out = self._rolling_avg4
            else:
                assert self._rolling_avg is not None, "just-updated EMA must be set"
                out = self._rolling_avg

            self._after_spike = max(0, self._after_spike - 1)

        self._prev_range = range_idx
        return out
