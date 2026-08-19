"""Hardware-in-the-loop tests for ``ppk2.client``.

Every test in this file is marked ``@pytest.mark.hardware`` — ``pytest``
skips them on the fast tier (default ``-m 'not hardware'``). Run with
``just test-hw`` (= ``pytest -m hardware``).

Hardware expected: a single PPK2 plugged in, in ammeter mode (in series
with an externally-powered DUT). The reference bench DUT
(``firmware/bench-dut/``) toggles D0 at 5 Hz and D1 at 0.5 Hz.
"""

from time import monotonic

import pytest

from ppk2 import (
    Mode,
    Sample,
    Session,
    find_ppk2,
)

pytestmark = pytest.mark.hardware


def test_discover_returns_a_port() -> None:
    """Smoke: ``find_ppk2`` returns a populated :class:`PortInfo`."""
    port = find_ppk2()
    assert port.device, "find_ppk2 returned an empty device path"
    assert port.usb_serial, "find_ppk2 returned an empty USB serial"


def test_session_open_returns_sane_metadata() -> None:
    """``Session.open`` runs the handshake and returns sensible coefficients."""
    port = find_ppk2()
    with Session.open(port.device) as session:
        coeffs = session.coefficients()
        assert coeffs.hw != 0, "HW manufacturing tag is zero"
        assert coeffs.ia != 0, "IA manufacturing tag is zero"
        for idx, gi in enumerate(coeffs.gi):
            assert gi != 0.0, f"GI[{idx}] is zero — parse drift?"


def test_capture_sample_rate_is_near_100ksps() -> None:
    """End-to-end capture: sustained rate is within ±10 % of 100 kSPS.

    Uses the capture path's calling convention (``latch_s=0`` +
    one-shot backlog drop), which deliberately keeps the
    FET-on/boot-inrush samples — so the first few hundred ms drain
    buffered catch-up above real-time. The rate is therefore measured
    over a 2 s window that starts after a 1 s warmup: it measures the
    stream, not the drain.
    """
    port = find_ppk2()
    with Session.open(port.device) as session:
        session.set_mode(Mode.AMPERE)
        session.set_source_voltage(3300)
        session.start_measuring()
        session.power_on(latch_s=0.0)
        session.drop_pending_backlog()

        started = monotonic()
        warmup_end = started + 1.0
        deadline = started + 3.0
        n_measured = 0
        measure_started: float | None = None

        def emit(_s: Sample) -> bool:
            nonlocal n_measured, measure_started
            now = monotonic()
            if now >= warmup_end:
                if measure_started is None:
                    measure_started = now
                n_measured += 1
            return now < deadline

        session.capture(emit)
        assert measure_started is not None, "no samples arrived after the 1 s warmup"
        measure_wall = monotonic() - measure_started

        session.power_off()
        session.stop_measuring()

    rate = n_measured / measure_wall
    assert 90_000.0 <= rate <= 110_000.0, (
        f"sustained sample rate {rate:.0f} Hz outside ±10 % of 100 kSPS "
        f"({n_measured} samples over {measure_wall:.3f} s post-warmup)"
    )


def test_capture_logic_byte_carries_d0_d1_activity() -> None:
    """The bench toggles D0 at 5 Hz and D1 at 0.5 Hz — capture for 3 s and verify."""
    port = find_ppk2()
    with Session.open(port.device) as session:
        session.set_mode(Mode.AMPERE)
        session.set_source_voltage(3300)
        session.start_measuring()
        session.power_on()

        seen_states: set[int] = set()
        union_high = 0
        deadline = monotonic() + 3.0

        def emit(s: Sample) -> bool:
            nonlocal union_high
            seen_states.add(s.logic)
            union_high |= s.logic
            return monotonic() < deadline

        session.capture(emit)
        session.power_off()
        session.stop_measuring()

    unused_mask = 0b1111_1100  # bits 2..=7 should stay zero on this bench
    assert union_high & unused_mask == 0, (
        f"bits 2-7 should stay 0 (D2-D7 wired floating?), got union 0b{union_high:08b}"
    )
    assert len(seen_states) >= 2, (
        f"no logic toggles in 3 s — expected D0/D1 activity, saw states {seen_states!r}"
    )
    assert union_high & 0b11 != 0, f"neither D0 nor D1 went high — union mask 0b{union_high:08b}"
