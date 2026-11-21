"""Hardware-in-the-loop tests for ``ppk2.client``.

Every test in this file is marked ``@pytest.mark.hardware``: ``just test``
deselects them (``-m 'not hardware'``). Run them with ``just test-hw``
(= ``pytest -m hardware``).

Hardware expected: a single PPK2 wired to a DUT running the reference
bench firmware (``bench-dut/``, next to this file), which toggles D0 at 5 Hz and
D1 at 0.5 Hz. The wiring decides the mode: Ampere meter by default
(PPK2 in series with an externally powered DUT); set
``PPK2_HIL_SOURCE_MV`` (e.g. ``3300``) for Source meter mode, when the
PPK2 powers the DUT.
"""

import os
from math import isnan
from time import monotonic, sleep

import pytest

from ppk2 import (
    Mode,
    Sample,
    Session,
    find_ppk2,
)

pytestmark = pytest.mark.hardware

_SOURCE_MV = os.environ.get("PPK2_HIL_SOURCE_MV")
_MODE = Mode.SOURCE if _SOURCE_MV else Mode.AMPERE
_VDD_MV = int(_SOURCE_MV) if _SOURCE_MV else 3300
_BENCH_HINT = "is the bench-dut firmware on the DUT, and the wiring the mode under test?"


def _configure(session: Session) -> None:
    session.set_mode(_MODE)
    session.set_source_voltage(_VDD_MV)


def _watch(session: Session, seconds: float) -> tuple[int, float]:
    """Capture for ``seconds``; return (D0 edges, mean current in µA)."""
    edges = 0
    previous: int | None = None
    total = 0.0
    count = 0
    deadline = monotonic() + seconds

    def emit(s: Sample) -> bool:
        nonlocal edges, previous, total, count
        d0 = s.logic & 1
        if previous is not None and d0 != previous:
            edges += 1
        previous = d0
        if not isnan(s.current_micro_amps):
            total += s.current_micro_amps
            count += 1
        return monotonic() < deadline

    session.capture(emit)
    return edges, total / max(count, 1)


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
            assert gi != 0.0, f"GI[{idx}] is zero: parse drift?"


def test_capture_sample_rate_is_near_100ksps() -> None:
    """End-to-end capture: sustained rate is within ±10 % of 100 kSPS.

    Uses the capture path's calling convention (``power_on`` and a
    one-shot backlog drop). The rate is measured over a 2 s window
    that starts after a 1 s warmup.
    """
    port = find_ppk2()
    with Session.open(port.device) as session:
        _configure(session)
        session.start_measuring()
        session.power_on()
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


def test_nothing_is_left_to_read_after_a_stop() -> None:
    """``stop_measuring`` reads the stream out: a restart begins with fresh samples.

    Left unread, about 5 ms of samples from before the stop would lead
    the next stream, with the sample counter carrying on as if nothing
    had happened.
    """
    port = find_ppk2()
    with Session.open(port.device) as session:
        _configure(session)
        for _round in range(3):
            session.start_measuring()
            seen = 0

            def emit(_s: Sample) -> bool:
                nonlocal seen
                seen += 1
                return seen < 20_000

            session.capture(emit)
            session.stop_measuring()
            sleep(0.1)
            assert session.drop_pending_backlog() == 0, (
                "bytes of the stopped stream were still waiting"
            )


def test_capture_logic_byte_carries_d0_d1_activity() -> None:
    """The bench toggles D0 at 5 Hz and D1 at 0.5 Hz: capture for 3 s and verify."""
    port = find_ppk2()
    with Session.open(port.device) as session:
        _configure(session)
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
        f"bits 2-7 should stay 0, got union 0b{union_high:08b} ({_BENCH_HINT})"
    )
    assert len(seen_states) >= 2, (
        f"no logic toggles in 3 s: expected D0/D1 activity, saw states {seen_states!r}"
    )
    assert union_high & 0b11 != 0, f"neither D0 nor D1 went high: union mask 0b{union_high:08b}"


def test_dut_is_unpowered_after_the_session_ends() -> None:
    """Leaving the ``with`` block cuts DUT power, with no explicit ``power_off``.

    The witness is a second session that starts the stream without
    switching power: a DUT that kept its power would still draw
    current (the bench firmware idles above 10 µA).
    """
    port = find_ppk2()
    with Session.open(port.device) as session:
        _configure(session)
        session.start_measuring()
        session.power_on()
        edges, _ = _watch(session, 1.0)
        assert edges >= 4, f"{edges} D0 edges in 1 s with the DUT powered ({_BENCH_HINT})"

    with Session.open(port.device) as session:
        _configure(session)
        session.start_measuring()
        _, mean_ua = _watch(session, 1.0)

    assert abs(mean_ua) < 2.0, f"DUT still draws {mean_ua:.1f} µA after the session ended"
