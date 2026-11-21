"""Wire opcodes.

Each opcode is one byte sent to the PPK2. The values are those of
Nordic's Power Profiler app (``pc-nrfconnect-ppk`` v4.4.1,
``src/constants.ts``).
"""

from enum import IntEnum


class Opcode(IntEnum):
    """Single-byte opcode; the enum value is the wire byte.

    ``Opcode.AVERAGE_START == 0x06``. ``byte()`` says the same thing at
    call sites.
    """

    TRIGGER_SET = 0x01
    """Generic ON parameter byte. Rarely sent as an opcode of its own."""

    AVG_NUM_SET = 0x02
    """Decimation count. Nordic flags it ``(no-firmware)``: the firmware
    ignores it."""

    TRIGGER_WINDOW_SET = 0x03
    """Triggered-capture window size (u16 LE)."""

    TRIGGER_INTERVAL_SET = 0x04
    """Triggered-capture interval (u16 LE). Nordic flags it
    ``(no-firmware)``."""

    TRIGGER_SINGLE_SET = 0x05
    """Single-shot trigger arm."""

    AVERAGE_START = 0x06
    """Start the 100 kSPS sample stream: 4-byte little-endian sample
    frames until ``AVERAGE_STOP``."""

    AVERAGE_STOP = 0x07
    """Stop the sample stream."""

    RANGE_SET = 0x08
    """Manual measurement-range override (u8, 0-4). Rarely used, the
    firmware auto-ranges. Nordic flags it ``(no-firmware)``."""

    LCD_SET = 0x09
    """LCD backlight. The PPK2 has no LCD; Nordic flags it
    ``(no-firmware)``."""

    DEVICE_RUNNING_SET = 0x0C
    """Power to the DUT: payload ``0x01`` on, ``0x00`` off. The app's "Enable power output".

    Applied about 1 ms after it is sent, with or without a stream. One
    sent within 0.31 s of ``AVERAGE_START`` is held until then (the
    protocol page, Known caveats).
    """

    REGULATOR_SET = 0x0D
    """Supply voltage in Source meter mode: ``[0x0D, mV >> 8, mV & 0xff]``
    (big-endian), 800-5000 mV.

    In Ampere meter mode the regulator is inactive, but the calibration
    still uses the last value sent (see ``current_micro_amps``).
    """

    SWITCH_POINT_DOWN = 0x0E
    """Auto-range hysteresis (downward)."""

    SWITCH_POINT_UP = 0x0F
    """Auto-range hysteresis (upward)."""

    SET_POWER_MODE = 0x11
    """Measurement mode: payload ``0x01`` Ampere meter, ``0x02`` Source meter.

    Nordic also names this byte ``TriggerExtToggle``, an
    external-trigger function that shares it; this library only uses it
    to set the mode.
    """

    RES_USER_SET = 0x12
    """User-supplied resistor calibration. No known host sends it."""

    SPIKE_FILTERING_ON = 0x15
    """Enable firmware-side spike filtering."""

    SPIKE_FILTERING_OFF = 0x16
    """Disable firmware-side spike filtering."""

    GET_METADATA = 0x19
    """Request the per-device calibration: ~1 KB of ASCII
    ``key: value\\n`` lines ending with ``END``."""

    RESET = 0x20
    """Soft-reset the firmware. The device drops off USB and
    re-enumerates (~200-500 ms on macOS)."""

    SET_USER_GAINS = 0x25
    """User gain override, payload ``[u8 range, f32 gain]``. Current
    firmware accepts and ignores it."""

    def byte(self) -> int:
        """Return the single byte sent on the wire for this opcode."""
        return int(self)

    # No @override: it lives in typing from 3.12 or in typing_extensions,
    # and this layer is stdlib-only on 3.11.
    def __repr__(self) -> str:  # pyright: ignore[reportImplicitOverride]
        """Show the value in hex: these are wire bytes."""
        return f"<{self.__class__.__name__}.{self.name}: 0x{self.value:02X}>"
