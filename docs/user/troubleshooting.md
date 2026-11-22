# Troubleshooting

## First check

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]
```

It shows every PPK2 the computer sees and the state of its two ports.
Most of the problems below show up here.

An error of `ppk2` is one line starting with `error:`, with exit code
1. Each section below begins with that line.

## No PPK2 found

```text
error: no PPK2 found (USB 1915:C00A): plug one in or check the cable
```

The computer does not see a PPK2 at all.

1. The cable. Some USB cables carry power only. The PPK2's LED lights
   up either way.
2. The socket on the PPK2. It must be `USB DATA/POWER`, not
   `USB POWER ONLY`.
3. The hub. Try a port on the computer itself.
4. What the system sees, with the table below.

| System | Look at | You should see |
|---|---|---|
| macOS | `ls /dev/cu.usbmodem*` | Two entries |
| Linux | `ls /dev/ttyACM*` | Two entries. If they are there but cannot be opened, see [the Linux note](getting-started.md#linux) |
| Windows | Device Manager, Ports | Two serial ports. Ports named after J-Link belong to a debugger |

The Linux and Windows rows have not been tried with a PPK2.

## Data port not identified

```text
error: could not identify the PPK2 data port: none of [...] answered GET_METADATA; close the nRF Connect Power Profiler if it is open, or pass --port to select the port explicitly
```

The ports are there, but none answered. The line names the ports in
place of `[...]`. The cause is another program holding the PPK2, nearly
always the Power Profiler app. `ppk2 list` then shows a port as
`[busy: held by another process?]`.

Quit the app, or disconnect the PPK2 inside it. If you know the path of
the data port, `--port` skips the search.

## Port busy

```text
close the nRF Connect Power Profiler, or whatever else holds the port
```

The same cause, met while opening the port: the system reported it as
busy. The line ends with these words.

## No PPK2 with that serial

```text
error: no PPK2 with serial A1B2C3D4E5F7: attached A1B2C3D4E5F6
```

A PPK2 is attached, but not the one `--serial` names. The line lists
the serial numbers that are there.

## Several PPK2s

```text
error: 2 physical PPK2 devices found; pass --serial <usb-serial> to pick one
```

Several PPK2s are attached. `ppk2 list` gives their serial numbers:

```sh
ppk2 list
ppk2 capture --serial A1B2C3D4E5F6 --out trace.csv --seconds 30
```

## No calibration received

```text
error: metadata recovery failed after 3 attempts; last: <cause>
```

The port opened but the PPK2 did not send its calibration. `ppk2` has
already asked again, with a `RESET` in between, and reopened the port.

- A capture that ended badly can leave the port stuck, on macOS in
  particular. Wait a few seconds and try again. If that fails, unplug
  the PPK2 and plug it back.
- Right after a process was killed, the system can refuse to open the
  port for a second or two.
- Another program that just used the PPK2 may still be closing it.

## No samples captured

```text
error: no samples captured: check the PPK2 mode and the DUT's power
```

The PPK2 answered but sent nothing during the capture. Check that the
mode matches the wiring: `--source` when the PPK2 supplies the DUT (device under test),
nothing when the DUT has its own supply.

## Output not writable

```text
error: /data/trace.csv: Permission denied
```

The output file could not be created or written. The line names the
path and gives the system's reason: a folder without write permission,
a full disk.

## Frames left by an unfinished run

```text
error: trace.ppk2.frames: left by a run that did not finish: move or delete it
```

An earlier capture or conversion to that `.ppk2` name did not finish
and left its samples in the `.frames` file, 6 bytes each. It is all
that remains of that run, so it is not overwritten. Move it away if
you want to keep it, or delete it, and run again.

## Capture ended short

```text
error: capture ended with 2999000 of 3000000 samples: the PPK2 stopped sending, or the computer did not keep up
```

The samples that `--seconds` asks for had not all arrived one second
after that time. The file holds what did arrive. A busy computer, a
USB hub or a long cable are the usual causes: see
[lost samples](#lost-samples-and-stream-rate-warnings).

## Current reads zero or far too low

- In Ampere meter mode, the current must pass through the PPK2: supply
  to `VIN`, `VOUT` to the DUT. A second path to the DUT is not
  measured.
- In Source meter mode, the DUT is off until a command switches it on,
  and off again when the command ends.
- Values below 0.2 µA are written as 0. That is the floor of the PPK2,
  not a fault.

## Digital inputs high while the DUT is off

They can. Without power on the DUT, the inputs are not driven.

## Lost samples and stream-rate warnings

The computer did not keep up with the PPK2. The trace keeps its
length, and each lost sample is recorded as 0.2 µA, as in Nordic's app,
which lowers sums and means in proportion. Try another USB port or
cable, without a hub, and close what else loads the machine.

## Calibrated: false

`ppk2 metadata` prints `Calibrated: false`. Not a fault. See
[the `Calibrated` flag](../measure/principle.md#calibrated-flag).

## Checking a measurement

Capture the same DUT with the app and with `ppk2 capture`, export the
app's capture as CSV, and compare the two files. The repository's
`validation/compare_cli.py` does it and writes a report. The
[validation](../validation/method.md) describes the procedure, and its
[results](../validation/results.md) show it on one dev kit, in both modes.

## See also

- [API reference](../develop/api.md): the errors as Python exceptions.
- [Protocol, known caveats](../measure/protocol.md#10-known-caveats)
