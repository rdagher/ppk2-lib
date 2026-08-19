"""CSV formatting helpers — GUI-parity 11-column output.

Mirrors the Nordic Power Profiler GUI's CSV export byte-for-byte:

    Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7
    0,2.846,10000000,1,0,0,0,0,0,0,0
    0.01,2.715,10000000,1,0,0,0,0,0,0,0

- Timestamp uses trimmed ``%.2f`` formatting — ``f"{t:.2f}"`` then
  ``.rstrip("0").rstrip(".")``. Coincides with ``%g`` for every
  timestamp the PPK2 actually emits (multiples of 0.01 ms), but is
  not strictly ``%g`` at sub-10-µs precision. Examples: ``0``,
  ``0.01``, ``0.1``, ``10``, ``1000``.
- ``D0-D7`` is an 8-character bit string with **D0 leftmost**.
- The per-pin ``D0``..``D7`` columns repeat each bit as a 0/1 boolean.
"""

from typing import TextIO

from ppk2.client.session import VOLTAGE_LIMIT_HARDWARE_MAX_MV, VOLTAGE_LIMIT_HARDWARE_MIN_MV

CSV_HEADER = "Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7"


def gui_noise_floor(current_ua: float) -> float:
    """The Nordic GUI's noise-floor clamp, applied at sample ingestion.

    Mirrors ``deviceActions.ts:333-337`` @ ``63ae4b7`` ("PPK 2 can only
    read till 200nA"): every calibrated value below 0.2 µA — including
    negative noise excursions — is recorded as exactly 0, before both
    the CSV row and the running stats. NaN data-loss placeholders pass
    through unchanged (``NaN < 0.2`` is false), preserving the
    skip-row path.
    """
    return 0.0 if current_ua < 0.2 else current_ua


def fmt_ts(t_ms: float) -> str:
    """Format a millisecond timestamp the way the Nordic GUI does.

    ``%.2f`` first, then trim trailing zeros and a trailing decimal
    point so a raw ``diff`` against a GUI export shows only real value
    differences, not formatting noise.
    """
    s = f"{t_ms:.2f}"
    trimmed = s.rstrip("0").rstrip(".")
    return trimmed if trimmed else "0"


def fmt_logic_d0d7(logic: int) -> str:
    """Format the logic byte as the GUI's 8-character ``D0-D7`` field.

    Position ``i`` is the state of pin ``Di``, D0 leftmost.
    """
    return "".join("1" if (logic >> i) & 1 else "0" for i in range(8))


def write_csv_row(out: TextIO, t_ms: float, current_ua: float, logic: int) -> None:
    """Emit one row in the GUI-parity 11-column format.

    NaN filtering is the caller's job: both capture loops skip
    data-loss placeholders (and count them) before calling this.
    """
    ts = fmt_ts(t_ms)
    d_str = fmt_logic_d0d7(logic)
    bits = ",".join(str((logic >> i) & 1) for i in range(8))
    out.write(f"{ts},{current_ua:.3f},{d_str},{bits}\n")


def vdd_to_mv(vdd: float) -> int:
    """Convert ``--vdd <volts>`` flag value into clamped mV the regulator accepts.

    Clamped to the hardware band (800-5000 mV) so the CLI can't talk
    the regulator into unsafe states; same constants the Session-level
    clamp uses.
    """
    return max(VOLTAGE_LIMIT_HARDWARE_MIN_MV, min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, round(vdd * 1000)))
