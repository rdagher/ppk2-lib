r"""Per-device calibration metadata returned by ``GET_META_DATA`` (0x19).

The response is multi-line ASCII (~1 KB) terminated by a literal
``END`` token. Each non-terminal line is ``key: value\n``. The parser
is chunked-read-aware in the sense that the caller is expected to
accumulate bytes until ``END`` is in the buffer before calling
[`parse_metadata`][].

Regression-tested against ``tests/fixtures/metadata.raw``, a real
response captured from a PPK2.
"""

from dataclasses import dataclass
from math import isfinite

# Fixed across the PPK2 product line: five hardware shunt ranges.
# (RangeArray and the unpack in _seal hardcode the same arity.)
NUM_RANGES = 5

# Type aliases for the 5-element fixed-length arrays. pyright enforces
# the length so missing or extra elements are caught at construction.
RangeArray = tuple[float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class CalibrationCoefficients:
    """Per-device calibration coefficients + runtime VDD/mode state.

    Bundles the factory-fit calibration arrays with the present
    ``REGULATOR_SET`` setpoint and power mode the firmware reported
    at metadata-read time.

    The calibration payload is strictly mandatory: [`parse_metadata`][]
    raises [`MissingField`][] when any coefficient array slot or
    version stamp is absent — silently defaulting a calibration value
    would corrupt every sample. The two *runtime-state* keys are the
    exception: ``VDD`` and ``mode`` get conservative defaults when the
    firmware omits them (observed on some firmware revisions), because
    they describe the device's present configuration, not its
    calibration.

    Attributes:
        calibrated: Internal Nordic manufacturing flag. A device reporting
            ``False`` still emits a fully populated coefficient block;
            this flag is NOT a "use defaults" signal.
        r: Per-range shunt resistance (Ω, virtual).
        gs: Per-range gain slope (quadratic term).
        gi: Per-range gain intercept (linear term).
        o: Per-range ADC offset (16-bit-equivalent counts).
        s: Per-range VDD-dependent linear slope.
        i: Per-range VDD-dependent linear intercept.
        ug: Per-range user gain override (default 1.0).
        vdd_mv: Current ``REGULATOR_SET`` setpoint in millivolts.
            Survives across host disconnects — a PPK2 last left in
            source mode at 1800 mV reports 1800 here on the next open.
            Range per firmware: 800..=5000 mV. Defaults to ``3300``
            when the firmware omits the ``VDD`` key.
        mode: Current power mode the firmware came up in: ``1`` =
            ammeter, ``2`` = source. Values outside ``{1, 2}`` raise
            [`InvalidValue`][]; a missing ``mode`` key defaults to
            ``1`` (ammeter — the PPK2's passive, can't-hurt-the-DUT
            mode).
        hw: Hardware version stamp.
        ia: Internal-Ammeter calibration version stamp.
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
    """A required key was absent from the response.

    ``field`` carries the human-readable field name (e.g. ``R[3]``).
    """

    def __init__(self, field: str) -> None:
        """Build a MissingField error tagged with the human-readable field name."""
        super().__init__(f"missing required metadata field: {field}")
        self.field = field


class InvalidValue(MetadataError):
    """A field was present but its value could not be parsed.

    ``field`` carries the human-readable field name; ``value`` is the
    raw string the parser refused.
    """

    def __init__(self, field: str, value: str) -> None:
        """Build an InvalidValue error capturing the field name and offending raw value."""
        super().__init__(f"invalid value for {field}: {value!r}")
        self.field = field
        self.value = value


def parse_metadata(buf: bytes) -> CalibrationCoefficients:
    r"""Parse a ``GET_META_DATA`` response into a populated coefficient block.

    Tolerates: unknown keys (forward-compat for future firmware
    revisions), both ``END`` and ``END\n`` terminators, excess
    whitespace around the ``:`` separator, missing ``VDD``/``mode``
    runtime-state keys (defaulted — see [`CalibrationCoefficients`][]),
    and undecodable leading residue. The residue case is real: binary
    sample-stream bytes from a badly shut-down prior session can
    precede the ASCII response, so the buffer is decoded with
    ``errors="replace"`` — garbage decodes into lines the key-value
    scan skips, instead of failing the whole parse.

    Strict on: missing calibration fields and malformed values of
    present keys.

    Args:
        buf: Raw bytes of the full ``GET_META_DATA`` response, accumulated
            across whatever USB chunks the OS delivered.

    Returns:
        Fully populated [`CalibrationCoefficients`][].

    Raises:
        MissingEnd: If ``buf`` does not contain the ``END`` terminator.
        MissingField: If a required calibration key is absent.
        InvalidValue: If a present field's value cannot be parsed.
    """
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

    Examples: ``"R0" → ("R", 0)``, ``"GS4" → ("GS", 4)``, ``"HW" → None``,
    ``"Calibrated" → None``.
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
    """Mutable accumulator used during parsing. Calls [`finish`][] to seal."""

    def __init__(self) -> None:
        """Initialise every slot to None; [`assign`][] fills them in."""
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
        # Per-range key?
        keyed = _split_keyed_index(key)
        if keyed is not None:
            prefix, idx = keyed
            if prefix not in _PER_RANGE_PREFIXES:
                # Unknown per-range prefix — forward-compat, skip.
                return
            if idx >= NUM_RANGES:
                # Forward-compat: a future 6-range firmware would emit
                # R5, etc.; we drop those silently rather than fail.
                return
            slot = self._slot_for(prefix)
            try:
                parsed = float(value)
            except ValueError as exc:
                raise InvalidValue(f"{prefix}[{idx}]", value) from exc
            # Real devices emit `-nan` for blank calibration slots
            # (Nordic's GUI maps them to factory defaults,
            # serialDevice.ts:340). A non-finite coefficient would
            # silently poison every sample into NaN; fail loud
            # instead of measuring garbage.
            if not isfinite(parsed):
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
        # Unknown scalar key (e.g. VERSION_OUT) — forward-compat, drop.

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
        # VDD and mode are runtime state, not calibration — some
        # firmware revisions omit them. Default conservatively: 3300 mV
        # (the nominal 3.3 V bench setpoint) and mode 1 (ammeter, the
        # passive mode). A present-but-garbage value still raises
        # InvalidValue in assign().
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
    """Convert a partial 5-element list into a fixed-length tuple.

    Raises [`MissingField`][] on the first absent slot.
    """
    out: list[float] = []
    for idx, value in enumerate(arr):
        if value is None:
            raise MissingField(f"{prefix}[{idx}]")
        out.append(value)
    # Unpack into a fixed 5-tuple so pyright sees the exact RangeArray length.
    a, b, c, d, e = out
    return (a, b, c, d, e)
