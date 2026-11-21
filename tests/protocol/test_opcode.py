"""Opcode enum byte-mapping tests.

Every opcode's enum value must match the literal wire byte the PPK2
firmware emits. The numbers are those of Nordic's `pc-nrfconnect-ppk`
(`src/constants.ts`).
"""

from ppk2 import Opcode


def test_opcode_bytes_match_protocol_reference() -> None:
    table: list[tuple[Opcode, int]] = [
        (Opcode.TRIGGER_SET, 0x01),
        (Opcode.AVG_NUM_SET, 0x02),
        (Opcode.TRIGGER_WINDOW_SET, 0x03),
        (Opcode.TRIGGER_INTERVAL_SET, 0x04),
        (Opcode.TRIGGER_SINGLE_SET, 0x05),
        (Opcode.AVERAGE_START, 0x06),
        (Opcode.AVERAGE_STOP, 0x07),
        (Opcode.RANGE_SET, 0x08),
        (Opcode.LCD_SET, 0x09),
        (Opcode.DEVICE_RUNNING_SET, 0x0C),
        (Opcode.REGULATOR_SET, 0x0D),
        (Opcode.SWITCH_POINT_DOWN, 0x0E),
        (Opcode.SWITCH_POINT_UP, 0x0F),
        (Opcode.SET_POWER_MODE, 0x11),
        (Opcode.RES_USER_SET, 0x12),
        (Opcode.SPIKE_FILTERING_ON, 0x15),
        (Opcode.SPIKE_FILTERING_OFF, 0x16),
        (Opcode.GET_METADATA, 0x19),
        (Opcode.RESET, 0x20),
        (Opcode.SET_USER_GAINS, 0x25),
    ]
    for op, expected in table:
        assert op.byte() == expected, f"{op!r} wire byte mismatch"
        assert int(op) == expected, f"{op!r} discriminant mismatch"


def test_intentionally_omitted_bytes_stay_omitted() -> None:
    """Bytes Nordic's app does not define: 0x00, 0x0a, 0x0b, 0x10."""
    all_opcodes = list(Opcode)
    omitted = {0x00, 0x0A, 0x0B, 0x10}
    for op in all_opcodes:
        assert int(op) not in omitted, f"{op!r} reuses an intentionally-omitted slot"
