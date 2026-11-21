# API reference

Every name on this page can be imported from `ppk2`. The text under
each one comes from its docstring. The
[architecture page](architecture.md) says how the pieces fit and how a
session goes.

## Discovery

`find_ppk2()` returns the data port of the one PPK2 attached. To get
there it:

1. lists the serial ports and keeps those with the PPK2's USB
   identity, `1915:C00A`;
2. groups them by USB serial number, since a PPK2 shows up as two
   ports;
3. asks each port for its calibration. Only the data port answers. If
   none does, it asks once more after a `RESET`.

If nothing is found it tries again for up to 3 seconds, because a PPK2
that was just plugged in takes a moment to appear. With several PPK2s
attached, use `find_ppk2_by_serial`, and `list_ppk2s` to see what is
there.

::: ppk2.client.discovery.find_ppk2

::: ppk2.client.discovery.find_ppk2_by_serial

::: ppk2.client.discovery.list_ppk2s

::: ppk2.client.discovery.PortInfo

::: ppk2.client.discovery.Ppk2Listing

::: ppk2.client.discovery.DiscoveryError

::: ppk2.client.discovery.NotFound

::: ppk2.client.discovery.Ambiguous

::: ppk2.client.discovery.DataPortNotFound

## Session

::: ppk2.client.session.Mode

::: ppk2.client.session.Session
    options:
      members:
        - open
        - close
        - coefficients
        - set_mode
        - set_source_voltage
        - set_voltage_limit
        - voltage_limit
        - start_measuring
        - stop_measuring
        - power_on
        - power_off
        - drop_pending_backlog
        - set_user_gain
        - set_spike_filter
        - spike_filter
        - capture

::: ppk2.client.session.SessionError

::: ppk2.client.session.SerialIOError

::: ppk2.client.session.HandshakeFailed

::: ppk2.client.session.VOLTAGE_LIMIT_HARDWARE_MIN_MV

::: ppk2.client.session.VOLTAGE_LIMIT_HARDWARE_MAX_MV

::: ppk2.client.session.USER_GAIN_MIN

::: ppk2.client.session.USER_GAIN_MAX

## Samples and stream parser

`StreamParser` is what a capture runs on. Give it the bytes of each
read, and it calls your function once per sample. It keeps the
alignment when a read ends in the middle of a word, follows the counter
of the samples, puts a placeholder where one was lost, and applies the
spike filter.

One call to `push_bytes` can produce no sample, one per word, or more.
It produces none when the bytes do not complete a word, or when a
sample is held back. It produces several when held samples are
released, or when placeholders fill a gap.

The parser does not care where the bytes come from. This decodes the
stream stored with the tests, using the calibration stored next to it:

```python
from pathlib import Path

from ppk2 import StreamParser, parse_metadata

coeffs = parse_metadata(Path("tests/fixtures/metadata.raw").read_bytes())
parser = StreamParser(coeffs, vdd_mv=3300)

currents: list[float] = []
parser.push_bytes(
    Path("tests/fixtures/stream_poweron.bin").read_bytes(),
    lambda sample: currents.append(sample.current_micro_amps),
)
print(f"{len(currents)} samples, mean {sum(currents) / len(currents):.2f} µA")
```

```text
600 samples, mean 5205.55 µA
```

::: ppk2.protocol.stream.Sample

::: ppk2.protocol.stream.SpikeFilter

::: ppk2.protocol.stream.StreamParser

## Raw samples

::: ppk2.protocol.sample.RawSample

::: ppk2.protocol.sample.decode_sample

::: ppk2.protocol.sample.decode_sample_bytes

## Calibration

::: ppk2.protocol.metadata.parse_metadata

::: ppk2.protocol.metadata.CalibrationCoefficients

::: ppk2.protocol.calibration.current_micro_amps

::: ppk2.protocol.metadata.MetadataError

::: ppk2.protocol.metadata.MissingEnd

::: ppk2.protocol.metadata.MissingField

::: ppk2.protocol.metadata.InvalidValue

## Commands

A command is one byte. The value of each member is the byte that goes
on the wire. The [protocol page](../measure/protocol.md#2-commands)
says what the PPK2 does with them.

::: ppk2.protocol.opcode.Opcode
