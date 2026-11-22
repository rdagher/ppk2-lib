"""Stateful byte-stream parser: alignment, counter resync, spike filter.

Feed raw serial bytes to ``StreamParser.push_bytes``; it calls back once
per emitted sample. Each 4-byte word goes through two stages:

1. Counter resync. A word with an out-of-range range field is
   dropped. A counter mismatch holds the sample back; the next in-sync
   sample releases what was held (those samples were real, just behind
   a brief gap). After ``MAX_BUFFERED_CORRUPTED`` mismatches in a row
   the gap is declared lost: NaN placeholders fill it, the held samples
   follow (they arrived after it), and the parser resyncs.
2. Spike filter. Two exponential moving averages (one for ranges
   0 to 3, a slower one for range 4) smooth the samples that follow a
   range change. Settings: ``SpikeFilter``.

When bytes are lost on the way, the stream can resume in the middle of
a word. The parser then looks for the byte offset at which the counters
run again, and resumes there (``_find_alignment``).

The resync logic is an independent implementation of
``handleRawDataSet`` in Nordic's app, with a few deliberate differences
listed in ``docs/measure/protocol.md`` (section 5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from math import nan
from struct import iter_unpack, pack, unpack_from

from ppk2.protocol.calibration import current_micro_amps
from ppk2.protocol.metadata import CalibrationCoefficients
from ppk2.protocol.sample import decode_sample


@dataclass(frozen=True, slots=True)
class Sample:
    """One calibrated, filtered sample.

    Attributes:
        current_micro_amps: Current in microamperes. NaN marks a lost
            sample: counter sync was not recovered in time.
        logic: Digital inputs D0 to D7 (bit 0 is D0); 0 for a lost sample.
    """

    current_micro_amps: float
    logic: int


#: Mismatched samples held before the gap is declared lost. Same as
#: Nordic's app.
MAX_BUFFERED_CORRUPTED = 5

#: Default EMA coefficient for ranges 0-3 (the app's "Coefficient for
#: range 1-4", ``spikeFilter.alpha``).
DEFAULT_SPIKE_FILTER_ALPHA: float = 0.18

#: Default EMA coefficient for range 4, the slow one (the app's
#: "Coefficient for range 5", ``spikeFilter.alpha5``).
DEFAULT_SPIKE_FILTER_ALPHA5: float = 0.06

#: Default number of samples smoothed after a range change (the app's
#: "Samples to smooth", ``spikeFilter.samples``).
DEFAULT_SPIKE_FILTER_SAMPLES: int = 3


@dataclass(frozen=True, slots=True)
class SpikeFilter:
    """Settings of the spike filter applied after a range change.

    The same three settings as the spike filter of Nordic's app, with
    the app's defaults. The app numbers the ranges 1 to 5; here they
    are 0 to 4, as in the stream.

    Attributes:
        samples: How many samples after a range change are smoothed
            (``>= 0``). The app's "Samples to smooth". A larger
            value smooths a transient more and follows a real change of
            level later.
        alpha: Coefficient of the moving average for ranges 0 to 3, in
            ``[0, 1]``. The app's
            "Coefficient for range 1-4".
        alpha5: Coefficient of the moving average for range 4, in
            ``[0, 1]``. The app's
            "Coefficient for range 5". This is the top range, 50 mA to
            1 A in the PPK2 user guide, and it gets the heavier
            smoothing.
    """

    samples: int = DEFAULT_SPIKE_FILTER_SAMPLES
    alpha: float = DEFAULT_SPIKE_FILTER_ALPHA
    alpha5: float = DEFAULT_SPIKE_FILTER_ALPHA5

    def __post_init__(self) -> None:
        if self.samples < 0:
            raise ValueError(f"samples must be >= 0, got {self.samples}")
        if not 0.0 <= self.alpha <= 1.0:
            raise ValueError(f"alpha must be in [0.0, 1.0], got {self.alpha}")
        if not 0.0 <= self.alpha5 <= 1.0:
            raise ValueError(f"alpha5 must be in [0.0, 1.0], got {self.alpha5}")


_COUNTER_MASK = 0x3F  # 6-bit counter, mod 64
_RANGE_MAX = 4
#: Words whose counters must follow one another for a byte offset to
#: count as the start of a word.
_ALIGN_WORDS = 8
_ALIGN_FORMAT = f"<{_ALIGN_WORDS}I"
_TOP_RANGE = 4  # 50 mA to 1 A: where the PPK2 jumps when the current rises fast


def _blend(average: float, reading: float, weight: float) -> float:
    """Move a running average towards ``reading`` by ``weight``."""
    return weight * reading + (1.0 - weight) * average


class _RangeChangeSmoother:
    """Replaces the readings that follow a range change by a running average.

    The PPK2 switches range as the current moves, and the readings right
    after a switch can be far off: on a DUT waking from sleep they
    reach an ampere for a few samples. For ``samples`` readings from
    each switch on, the output is a running average instead of the
    reading. Two averages run all the time, a quick one for ranges 0-3
    and a heavier one for range 4; in range 4 the first two readings
    after the switch are kept out of the averages as well.

    Same output as the spike filter of Nordic's app, setting for setting.
    """

    def __init__(self, knobs: SpikeFilter) -> None:
        self._knobs = knobs
        self._quick = 0.0
        self._heavy = 0.0
        self._range: int | None = None  # range of the previous reading
        self._since_switch = 0  # readings in the present range since the switch
        self._left = 0  # readings still to replace

    def next(self, range_idx: int, ua: float) -> float:
        """Take one reading in µA; return it, or the average that replaces it."""
        if self._range is None:
            self._quick = self._heavy = ua
            self._range = range_idx
            return ua

        before = (self._quick, self._heavy)
        self._quick = _blend(self._quick, ua, self._knobs.alpha)
        self._heavy = _blend(self._heavy, ua, self._knobs.alpha5)

        if range_idx != self._range:
            self._range = range_idx
            self._since_switch = 0
            self._left = self._knobs.samples
        elif self._left > 0:
            self._since_switch += 1
        else:
            return ua

        self._left = max(0, self._left - 1)
        if range_idx != _TOP_RANGE:
            return self._quick
        if self._since_switch < 2:
            self._quick, self._heavy = before
        return self._heavy


# Placeholder for a lost sample. logic is 0: there is no signal to report.
_NAN_SAMPLE = Sample(current_micro_amps=nan, logic=0)


class StreamParser:
    """Turns the PPK2 byte stream into ``Sample`` objects; one per capture.

    Reads need not land on 4-byte boundaries: up to 3 trailing bytes are
    kept and prepended to the next ``push_bytes`` call. The reads
    seen on the bench have come back aligned. The remainder is for those
    that do not: another system, a read that times out in the middle of
    a word, a test.
    """

    def __init__(
        self,
        coeffs: CalibrationCoefficients,
        vdd_mv: int,
        spike_filter: SpikeFilter | None = None,
    ) -> None:
        """Build a parser.

        Args:
            coeffs: Calibration from ``parse_metadata``.
            vdd_mv: Present supply voltage in millivolts.
            spike_filter: Filter settings; the app's defaults when
                ``None``.
        """
        self._coeffs = coeffs
        self._vdd_mv = vdd_mv
        self._spike_filter = spike_filter if spike_filter is not None else SpikeFilter()
        self._smoother = _RangeChangeSmoother(self._spike_filter)
        # Bytes carried to the next call: 0-3 short of a word, or more
        # while an alignment is being searched.
        self._remainder = bytearray()
        # Counter-resync state.
        self._expected_counter: int | None = None
        self._corruption_buffer: list[Sample] = []
        # Since the last sample in step: the counters of the held
        # samples, the bytes of every word seen, the counter that was due.
        self._held_counters: list[int] = []
        self._suspect = bytearray()
        self._due_counter = 0
        self._realigning = False
        #: NaN placeholders emitted so far. Never decreases: compare
        #: before and after a ``push_bytes`` call to spot new losses.
        self.dataloss_total: int = 0

    def push_bytes(self, buf: bytes, emit: Callable[[Sample], None]) -> None:
        """Feed bytes from a serial read; call ``emit`` for each sample they complete.

        One call can emit nothing (bytes short of a word, or a sample
        held back for resync) or several samples per word (held samples
        released, or placeholders for a lost gap).
        """
        if self._remainder:
            self._remainder.extend(buf)
            data = bytes(self._remainder)
            self._remainder.clear()
        else:
            data = buf
        pos = 0
        while True:
            if self._realigning:
                pos = self._find_alignment(data, pos)
                if pos < 0:
                    return
                self._resume_at(data, pos, emit)
            whole = (len(data) - pos) & ~3
            # iter_unpack runs the loop in C.
            words = iter_unpack("<I", memoryview(data)[pos : pos + whole])
            for i, (raw,) in enumerate(words):
                if not self._consume_word(raw, emit):
                    # Alignment lost: search again from the first word
                    # in doubt, one byte further on.
                    data = bytes(self._suspect) + bytes(data[pos + 4 * (i + 1) :])
                    self._suspect.clear()
                    self._realigning = True
                    pos = 1
                    break
            else:
                if pos + whole < len(data):
                    self._remainder.extend(data[pos + whole :])
                return

    def _find_alignment(self, data: bytes, start: int) -> int:
        """Return the first offset from ``start`` where ``_ALIGN_WORDS`` words follow one another.

        Returns -1 when ``data`` is too short to tell, after keeping the
        bytes not yet ruled out for the next call.
        """
        last = len(data) - 4 * _ALIGN_WORDS
        pos = start
        while pos <= last:
            words = unpack_from(_ALIGN_FORMAT, data, pos)
            counter = (words[0] >> 18) & _COUNTER_MASK
            for word in words:
                if (word >> 14) & 0x7 > _RANGE_MAX or (word >> 18) & _COUNTER_MASK != counter:
                    break
                counter = (counter + 1) & _COUNTER_MASK
            else:
                return pos
            pos += 1
        self._remainder.extend(data[pos:])
        return -1

    def _resume_at(self, data: bytes, pos: int, emit: Callable[[Sample], None]) -> None:
        """Fill the gap up to the word at ``pos`` and start afresh from it."""
        (word,) = unpack_from("<I", data, pos)
        # The counter gives the gap modulo 64 only. Bytes were lost, so
        # a gap of 0 is 64 at least.
        gap = (((word >> 18) & _COUNTER_MASK) - self._due_counter) & _COUNTER_MASK or 64
        for _ in range(gap):
            emit(_NAN_SAMPLE)
        self.dataloss_total += gap
        self._expected_counter = None
        self._corruption_buffer.clear()
        self._held_counters.clear()
        # The words in doubt went through the filter: start it afresh.
        self._smoother = _RangeChangeSmoother(self._spike_filter)
        self._realigning = False

    def _consume_word(self, raw: int, emit: Callable[[Sample], None]) -> bool:
        """Process one 4-byte word; emit zero, one, or many samples.

        Returns False when the word shows that the alignment is lost.
        """
        raw_sample = decode_sample(raw)

        # A range above 4 cannot index the calibration arrays. Alone,
        # the word is dropped without touching the counter state (Nordic
        # clamps the range and lets it through). After a mismatch, it
        # means the alignment is lost.
        if not raw_sample.range_valid():
            if self._expected_counter is None:
                return True
            if not self._suspect:
                self._due_counter = self._expected_counter
            self._suspect.extend(pack("<I", raw))
            return not self._held_counters
        counter = raw_sample.counter

        # Calibrate and filter before routing on the counter: the filter
        # state must advance per input sample, so a held sample keeps
        # the value it had on arrival. Same order as Nordic's
        # handleRawDataSet.
        raw_ua = current_micro_amps(
            raw_sample.adc_14,
            raw_sample.range,
            self._vdd_mv,
            self._coeffs,
        )
        smoothed_ua = self._smoother.next(raw_sample.range, raw_ua)
        sample = Sample(current_micro_amps=smoothed_ua, logic=raw_sample.logic)

        # First valid sample: seed the expected counter and emit.
        if self._expected_counter is None:
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            emit(sample)
            return True

        # In sync: release any held samples first (they were real, just
        # behind a brief gap), then emit this one.
        if counter == self._expected_counter:
            if self._suspect:
                for buffered in self._corruption_buffer:
                    emit(buffered)
                self._corruption_buffer.clear()
                self._held_counters.clear()
                self._suspect.clear()
            emit(sample)
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            return True

        # Buffer full and still out of sync: the gap is lost. Fill it
        # with placeholders, then release the held samples (they arrived
        # after the gap) and this one, and resync on this counter.
        if len(self._corruption_buffer) >= MAX_BUFFERED_CORRUPTED:
            # Samples from after a gap follow one another. If the held
            # ones do not, they are not samples: the alignment is lost.
            follows = self._held_counters[0]
            for held in (*self._held_counters, counter):
                if held != follows:
                    self._suspect.extend(pack("<I", raw))
                    return False
                follows = (follows + 1) & _COUNTER_MASK
            # The mod-64 distance. Nordic's app counts one less.
            gap = (counter - self._expected_counter) & _COUNTER_MASK
            for _ in range(gap):
                emit(_NAN_SAMPLE)
            self.dataloss_total += gap
            for buffered in self._corruption_buffer:
                emit(buffered)
            self._corruption_buffer.clear()
            self._held_counters.clear()
            self._suspect.clear()
            emit(sample)
            self._expected_counter = (counter + 1) & _COUNTER_MASK
            return True

        # Out of sync with room left: hold the sample back until the
        # stream resyncs or the gap is declared lost. (Nordic also emits
        # it here, which duplicates it on a resync.)
        if not self._suspect:
            self._due_counter = self._expected_counter
        self._corruption_buffer.append(sample)
        self._held_counters.append(counter)
        self._suspect.extend(pack("<I", raw))
        self._expected_counter = (self._expected_counter + 1) & _COUNTER_MASK
        return True
