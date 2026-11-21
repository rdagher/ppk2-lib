"""CSV output in the 11-column format of Nordic's Power Profiler app.

    Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7
    0,2.846,10000000,1,0,0,0,0,0,0,0
    0.01,2.715,10000000,1,0,0,0,0,0,0,0

- The timestamp is ``%.2f`` with trailing zeros and a trailing point
  trimmed: ``0``, ``0.01``, ``0.1``, ``10``.
- ``D0-D7`` is an 8-character bit string with **D0 leftmost**.
- The ``D0``..``D7`` columns repeat each bit as 0 or 1.
"""

from typing import TextIO

from ppk2.client.session import VOLTAGE_LIMIT_HARDWARE_MAX_MV, VOLTAGE_LIMIT_HARDWARE_MIN_MV

CSV_HEADER = "Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7"


def noise_floor(current_ua: float) -> float:
    """The noise-floor clamp of Nordic's app: anything below 0.2 µA becomes 0.

    As the app does, negative noise included. It applies before both
    the file and the running mean. NaN (a lost sample) passes through.
    """
    return 0.0 if current_ua < 0.2 else current_ua


def fmt_ts(t_ms: float) -> str:
    """Format a millisecond timestamp the way Nordic's app does.

    ``%.2f``, then trailing zeros and a trailing point trimmed, so the
    column matches the app's export character for character.
    """
    s = f"{t_ms:.2f}"
    trimmed = s.rstrip("0").rstrip(".")
    return trimmed if trimmed else "0"


def fmt_logic_d0d7(logic: int) -> str:
    """Format the logic byte as the app's 8-character ``D0-D7`` field, D0 leftmost."""
    return "".join("1" if (logic >> i) & 1 else "0" for i in range(8))


def write_csv_row(out: TextIO, t_ms: float, current_ua: float, logic: int) -> None:
    """Write one row in the 11-column format.

    ``TraceFile`` turns a lost sample (NaN) into 0.2 µA before it gets here.
    """
    ts = fmt_ts(t_ms)
    d_str = fmt_logic_d0d7(logic)
    bits = ",".join(str((logic >> i) & 1) for i in range(8))
    out.write(f"{ts},{current_ua:.3f},{d_str},{bits}\n")


def vdd_to_mv(vdd: float) -> int:
    """Convert ``--vdd`` volts to millivolts, clamped to the regulator's 800-5000 mV."""
    return max(VOLTAGE_LIMIT_HARDWARE_MIN_MV, min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, round(vdd * 1000)))
