"""Wire opcodes — single source of truth.

Each opcode is one byte sent over USB CDC to the PPK2 firmware.
Cross-referenced against Nordic's ``pc-nrfconnect-ppk`` (``@ 63ae4b7``,
``src/constants.ts``) and IRNAS's ``ppk2-api-python`` (``v0.9.2``).

Two bytes are intentionally omitted:

- ``NO_OP (0x00)`` — declared in IRNAS but never sent as a standalone
  opcode (it doubles as the implicit OFF parameter byte). Send the raw
  byte when you mean it.
- ``TriggerStop (0x0a)`` — Nordic dropped this between earlier revisions
  and the SHA we pin against; firmware-side status unknown.
"""

from enum import IntEnum


class Opcode(IntEnum):
    """Single-byte opcode sent over USB CDC to the PPK2 firmware.

    The enum value is the literal wire byte —
    ``int(Opcode.AVERAGE_START) == 0x06``. The [`byte`][] helper is a
    clearer name for the same coercion at call sites.
    """

    TRIGGER_SET = 0x01
    """``0x01`` — Generic-purpose ON parameter byte. Rarely sent as a
    primary opcode."""

    AVG_NUM_SET = 0x02
    """``0x02`` — Firmware-side decimation count. Nordic flags this
    ``(no-firmware)`` in their enum; v1 host implementations send 0 to
    mean "full 100 kSPS, no decimation"."""

    TRIGGER_WINDOW_SET = 0x03
    """``0x03`` — Triggered-capture window size (u16 LE)."""

    TRIGGER_INTERVAL_SET = 0x04
    """``0x04`` — Triggered-capture interval (u16 LE). Nordic flags
    ``(no-firmware)``."""

    TRIGGER_SINGLE_SET = 0x05
    """``0x05`` — Single-shot trigger arm."""

    AVERAGE_START = 0x06
    """``0x06`` — Start the 100 kSPS sample stream.

    Response: continuous 4-byte little-endian sample frames until
    [`AVERAGE_STOP`][] is sent.
    """

    AVERAGE_STOP = 0x07
    """``0x07`` — Stop the sample stream."""

    RANGE_SET = 0x08
    """``0x08`` — Manual measurement-range override (u8, 0..=4). Rarely
    used — firmware auto-ranges. Nordic flags ``(no-firmware)``."""

    LCD_SET = 0x09
    """``0x09`` — LCD backlight (PPK2 has no LCD; Nordic flags
    ``(no-firmware)``)."""

    DEVICE_RUNNING_SET = 0x0C
    """``0x0C`` — DUT-power FET toggle.

    Payload ``0x01`` = ON, ``0x00`` = OFF. Requires the sample stream to be
    active and ~200 ms elapsed since [`AVERAGE_START`][], otherwise the
    firmware silently drops the command.
    """

    REGULATOR_SET = 0x0D
    """``0x0D`` — Source-mode VDD setpoint. In ammeter mode the
    regulator is inactive, but host-side calibration still uses the
    last value sent (see [`current_micro_amps`][ppk2.protocol.current_micro_amps]).

    Wire format: ``[0x0D, vdd_mV >> 8, vdd_mV & 0xff]`` (big-endian 16-bit
    mV). Valid range 800..=5000 mV.
    """

    SWITCH_POINT_DOWN = 0x0E
    """``0x0E`` — Auto-range hysteresis (downward)."""

    SWITCH_POINT_UP = 0x0F
    """``0x0F`` — Auto-range hysteresis (upward)."""

    SET_POWER_MODE = 0x11
    """``0x11`` — Measurement mode selector. Payload ``0x01`` = ammeter,
    ``0x02`` = source.

    Nordic and IRNAS both alias this opcode under the name
    ``TriggerExtToggle`` for an external-trigger function that shares the
    wire byte; v1 treats ``0x11`` as ``SetPowerMode`` only.
    """

    RES_USER_SET = 0x12
    """``0x12`` — User-supplied resistor calibration. Speculative — no host
    implementation actually emits this."""

    SPIKE_FILTERING_ON = 0x15
    """``0x15`` — Enable firmware-side spike filtering."""

    SPIKE_FILTERING_OFF = 0x16
    """``0x16`` — Disable firmware-side spike filtering."""

    GET_METADATA = 0x19
    """``0x19`` — Request per-device calibration metadata.

    Response: ~1 KB of ASCII ``key: value\\n`` lines terminated by
    ``END``.
    """

    RESET = 0x20
    """``0x20`` — Soft-reset the firmware. Triggers a ~200-500 ms USB CDC
    re-enumeration on macOS."""

    SET_USER_GAINS = 0x25
    """``0x25`` — User gain override. Payload ``[u8 range, f32 gain]``."""

    def byte(self) -> int:
        """Return the single byte sent on the wire for this opcode."""
        return int(self)

    # reportImplicitOverride is structurally unsatisfiable here: the rule
    # wants `@override`, which lives in `typing` from Python 3.12+ or in
    # `typing_extensions` before that. We pin `requires-python = ">=3.11"`
    # and the protocol layer is stdlib-only by design, so neither path is
    # available. Suppression is scoped to this single method.
    def __repr__(self) -> str:  # pyright: ignore[reportImplicitOverride]
        """Render the value in hex — these are wire bytes, hex is what reads."""
        return f"<{self.__class__.__name__}.{self.name}: 0x{self.value:02X}>"
