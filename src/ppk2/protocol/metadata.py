r"""Per-device calibration metadata returned by ``GET_META_DATA`` (0x19).

The response is ~1 KB of ASCII ``key: value\n`` lines ending with a
literal ``END``. It can arrive split across reads: accumulate until
``END`` is in the buffer, then call ``parse_metadata``.

Regression-tested against ``tests/fixtures/metadata.raw``, a real
response captured from a PPK2.
"""

from dataclasses import dataclass
from math import isfinite, isnan

# Five measurement ranges, fixed across the PPK2 line.
NUM_RANGES = 5

# One value per range; a fixed-length tuple, so pyright checks the count.
RangeArray = tuple[float, float, float, float, float]

# The response starts with this key; what precedes it is not metadata.
_FIRST_KEY = b"Calibrated"

# What Nordic's Power Profiler app assumes for a slot the device left
# blank (the firmware prints ``-nan`` for one): nominal resistances,
# unit gains, no offsets.
_BLANK_DEFAULTS: dict[str, RangeArray] = {
    "R": (1031.64, 101.65, 10.15, 0.94, 0.043),
    "GS": (1.0, 1.0, 1.0, 1.0, 1.0),
    "GI": (1.0, 1.0, 1.0, 1.0, 1.0),
    "O": (0.0, 0.0, 0.0, 0.0, 0.0),
    "S": (0.0, 0.0, 0.0, 0.0, 0.0),
    "I": (0.0, 0.0, 0.0, 0.0, 0.0),
    "UG": (1.0, 1.0, 1.0, 1.0, 1.0),
}


@dataclass(frozen=True, slots=True)
class CalibrationCoefficients:
    """Per-device calibration, plus the VDD and mode the firmware reported.

    Every coefficient is mandatory: a defaulted calibration value would
    corrupt every sample, so ``parse_metadata`` raises ``MissingField``
    instead. ``VDD`` and ``mode`` describe the device's present state,
    not its calibration, and some firmware revisions omit them: those
    two get defaults.

    Attributes:
        calibrated: The ``Calibrated`` value as reported. Not
            interpreted: a PPK2 that reports ``False`` still carries a
            full set of coefficients, and they are used.
        r: Per-range resistance (Ω, virtual).
        gs: Per-range gain slope (quadratic term).
        gi: Per-range gain intercept (linear term).
        o: Per-range ADC offset (16-bit-equivalent counts).
        s: Per-range VDD-dependent linear slope.
        i: Per-range VDD-dependent linear intercept.
        ug: Per-range user gain (default 1.0).
        vdd_mv: Supply voltage in millivolts, 800-5000: the last
            ``REGULATOR_SET``. It survives host disconnects: a PPK2
            left at 1800 mV reports 1800 on the next open. 3300 when
            the firmware omits it.
        mode: Power mode, ``1`` Ampere meter or ``2`` Source meter;
            anything else raises ``InvalidValue``. Ampere meter, the
            passive mode, when the firmware omits it.
        hw: The ``HW`` value as reported. Not interpreted.
        ia: The ``IA`` value as reported. Not interpreted.
    """

    calibrated: bool
    r: RangeArray
    gs: RangeArray
    gi: RangeArray
    o: RangeArray
    s: RangeArray
    i: RangeArray
    ug: RangeArray
    vdd_mv: int
    mode: int
    hw: int
    ia: int


class MetadataError(Exception):
    """Base class for metadata-parse failures."""


class MissingEnd(MetadataError):
    """Buffer did not contain the ``END`` terminator.

    The caller's accumulating-read loop has a bug.
    """


class MissingField(MetadataError):
    """A required key was absent; ``field`` names it (e.g. ``R[3]``)."""

    def __init__(self, field: str) -> None:
        super().__init__(f"missing required metadata field: {field}")
        self.field = field


class InvalidValue(MetadataError):
    """A field's value could not be parsed; ``value`` is the raw text."""

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f"invalid value for {field}: {value!r}")
        self.field = field
        self.value = value


def parse_metadata(buf: bytes) -> CalibrationCoefficients:
    r"""Parse a full ``GET_META_DATA`` response into calibration coefficients.

    Tolerant of unknown keys, ``END`` with or without a newline, spaces
    around the ``:``, missing ``VDD``/``mode`` (see
    ``CalibrationCoefficients``), and bytes before the text: the end
    of a stream that was not read out, up to 1 kB of samples, can come
    glued in front of the response. The parse starts at the first key,
    ``Calibrated``.

    Strict on missing calibration fields and on malformed values. A
    blank slot (``-nan``) takes the default Nordic's app uses for it.

    Raises:
        MissingEnd: If ``buf`` has no ``END`` terminator.
        MissingField: If a calibration key is absent.
        InvalidValue: If a present field's value cannot be parsed.
    """
    start = buf.find(_FIRST_KEY)
    if start > 0:
        buf = buf[start:]
    text = buf.decode("utf-8", errors="replace")

    partial = _Partial()
    saw_end = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line == "END":
            saw_end = True
            break
        kv = _split_kv(line)
        if kv is None:
            # Lines without `:` are silently skipped (forward-compat).
            continue
        key, value = kv
        partial.assign(key, value)

    if not saw_end:
        raise MissingEnd("no END terminator in metadata buffer")

    return partial.finish()


# ─── internals ─────────────────────────────────────────────────────────


def _split_kv(line: str) -> tuple[str, str] | None:
    """Split a line on the first ``:``; return ``(key, value)`` trimmed."""
    if ":" not in line:
        return None
    k, _, v = line.partition(":")
    return k.strip(), v.strip()


_PER_RANGE_PREFIXES = ("R", "GS", "GI", "O", "S", "I", "UG")


def _split_keyed_index(key: str) -> tuple[str, int] | None:
    """Split a per-range key into prefix + numeric suffix.

    Examples: ``"R0" -> ("R", 0)``, ``"GS4" -> ("GS", 4)``, ``"HW" -> None``,
    ``"Calibrated" -> None``.
    """
    # Walk back from the end while digits, then take the suffix.
    suffix_start = len(key)
    while suffix_start > 0 and key[suffix_start - 1].isdigit():
        suffix_start -= 1
    if suffix_start == 0 or suffix_start == len(key):
        return None
    prefix = key[:suffix_start]
    try:
        idx = int(key[suffix_start:])
    except ValueError:
        return None
    return prefix, idx


class _Partial:
    """Mutable accumulator: ``assign`` fills it, ``finish`` seals it."""

    def __init__(self) -> None:
        self.calibrated: bool | None = None
        self.r: list[float | None] = [None] * NUM_RANGES
        self.gs: list[float | None] = [None] * NUM_RANGES
        self.gi: list[float | None] = [None] * NUM_RANGES
        self.o: list[float | None] = [None] * NUM_RANGES
        self.s: list[float | None] = [None] * NUM_RANGES
        self.i: list[float | None] = [None] * NUM_RANGES
        self.ug: list[float | None] = [None] * NUM_RANGES
        self.vdd_mv: int | None = None
        self.mode: int | None = None
        self.hw: int | None = None
        self.ia: int | None = None

    def assign(self, key: str, value: str) -> None:
        keyed = _split_keyed_index(key)
        if keyed is not None:
            prefix, idx = keyed
            if prefix not in _PER_RANGE_PREFIXES:
                # An unknown array: ignored.
                return
            if idx >= NUM_RANGES:
                # A sixth range and beyond: ignored.
                return
            slot = self._slot_for(prefix)
            try:
                parsed = float(value)
            except ValueError as exc:
                raise InvalidValue(f"{prefix}[{idx}]", value) from exc
            if isnan(parsed):
                # A slot the device left blank: the app's default, as
                # the app does. A NaN kept here would turn every sample
                # of that range into NaN.
                parsed = _BLANK_DEFAULTS[prefix][idx]
            elif not isfinite(parsed):
                raise InvalidValue(f"{prefix}[{idx}]", value)
            slot[idx] = parsed
            return

        # Scalar keys. Names match the wire-format exactly (PPK2 firmware
        # is case-sensitive: `VDD` upper, `mode` lower).
        if key == "Calibrated":
            if value == "0":
                self.calibrated = False
            elif value == "1":
                self.calibrated = True
            else:
                raise InvalidValue("Calibrated", value)
        elif key == "HW":
            try:
                self.hw = int(value)
            except ValueError as exc:
                raise InvalidValue("HW", value) from exc
        elif key == "IA":
            try:
                self.ia = int(value)
            except ValueError as exc:
                raise InvalidValue("IA", value) from exc
        elif key == "VDD":
            try:
                self.vdd_mv = int(value)
            except ValueError as exc:
                raise InvalidValue("VDD", value) from exc
        elif key == "mode":
            try:
                parsed_mode = int(value)
            except ValueError as exc:
                raise InvalidValue("mode", value) from exc
            if parsed_mode not in (1, 2):
                raise InvalidValue("mode", value)
            self.mode = parsed_mode
        # Unknown scalar key (e.g. VERSION_OUT): forward-compat, drop.

    def _slot_for(self, prefix: str) -> list[float | None]:
        # Mapping kept explicit so pyright knows every branch returns
        # a typed list (no Any fallback).
        if prefix == "R":
            return self.r
        if prefix == "GS":
            return self.gs
        if prefix == "GI":
            return self.gi
        if prefix == "O":
            return self.o
        if prefix == "S":
            return self.s
        if prefix == "I":
            return self.i
        if prefix == "UG":
            return self.ug
        raise AssertionError(f"unreachable: caller already filtered prefix={prefix!r}")

    def finish(self) -> CalibrationCoefficients:
        if self.calibrated is None:
            raise MissingField("Calibrated")
        if self.hw is None:
            raise MissingField("HW")
        if self.ia is None:
            raise MissingField("IA")
        # VDD and mode are state, not calibration, and may be absent:
        # then 3300 mV and Ampere meter mode.
        return CalibrationCoefficients(
            calibrated=self.calibrated,
            r=_seal("R", self.r),
            gs=_seal("GS", self.gs),
            gi=_seal("GI", self.gi),
            o=_seal("O", self.o),
            s=_seal("S", self.s),
            i=_seal("I", self.i),
            ug=_seal("UG", self.ug),
            vdd_mv=self.vdd_mv if self.vdd_mv is not None else 3300,
            mode=self.mode if self.mode is not None else 1,
            hw=self.hw,
            ia=self.ia,
        )


def _seal(prefix: str, arr: list[float | None]) -> RangeArray:
    """Turn a filled 5-slot list into a ``RangeArray``; ``MissingField`` on a gap."""
    out: list[float] = []
    for idx, value in enumerate(arr):
        if value is None:
            raise MissingField(f"{prefix}[{idx}]")
        out.append(value)
    # Unpack into a fixed 5-tuple so pyright sees the exact RangeArray length.
    a, b, c, d, e = out
    return (a, b, c, d, e)
