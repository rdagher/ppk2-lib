# Troubleshooting

## Start with `ppk2 list`

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]
```

It shows every PPK2 the computer sees and the state of its two ports.
Most of the problems below show up here.

Errors of `ppk2` are one line starting with `error:`, with exit code 1.
The headings below are those lines.

## `no PPK2 found (USB 1915:C00A): plug one in or check the cable`

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

## `could not identify the PPK2 data port`

The ports are there, but none answered. The full line names the ports
and suggests the cause: another program holds the PPK2, nearly always
the Power Profiler app. `ppk2 list` then shows a port as
`[busy: held by another process?]`.

Quit the app, or disconnect the PPK2 inside it. If you know the path of
the data port, `--port` skips the search.

## A message ending in `close the nRF Connect Power Profiler, or whatever else holds the port`

The same cause, met while opening the port: the system reported it as
busy.

## `N physical PPK2 devices found; pass --serial <usb-serial> to pick one`

Several PPK2s are attached. `ppk2 list` gives their serial numbers:

```sh
ppk2 list
ppk2 capture --serial A1B2C3D4E5F6 --out trace.csv --seconds 30
```

## `metadata recovery failed after 3 attempts`

The port opened but the PPK2 did not send its calibration. `ppk2` has
already asked again, with a `RESET` in between, and reopened the port.

- A capture that ended badly can leave the port stuck, on macOS in
  particular. Wait a few seconds and try again. If that fails, unplug
  the PPK2 and plug it back.
- Right after a process was killed, the system can refuse to open the
  port for a second or two.
- Another program that just used the PPK2 may still be closing it.

## `no samples captured: check the PPK2 mode and the DUT's power`

The PPK2 answered but sent nothing during the capture. Check that the
mode matches the wiring: `--source` when the PPK2 supplies the DUT,
nothing when the DUT has its own supply.

## The current reads zero, or far too low

- In Ampere meter mode, the current must pass through the PPK2: supply
  to `VIN`, `VOUT` to the DUT. A second path to the DUT is not
  measured.
- In Source meter mode, the DUT is off until a command switches it on,
  and off again when the command ends.
- Values below 0.2 µA are written as 0. That is the floor of the PPK2,
  not a fault.

## The digital inputs read high while the DUT is off

They can. Without power on the DUT, the inputs are not driven.

## Warnings about lost samples or the stream rate

The computer did not keep up with the PPK2. The trace keeps its
length, and each lost sample is recorded as 0.2 µA, as in Nordic's app,
which lowers sums and means in proportion. Try another USB port or
cable, without a hub, and close what else loads the machine.

## `Calibrated: false`

Not a fault. See
[the `Calibrated` flag](../measure/principle.md#the-calibrated-flag).

## Is it measuring right?

Capture the same DUT with the app and with `ppk2 capture`, export the
app's capture as CSV, and compare the two files. The repository's
`validation/compare_cli.py` does it and writes a report. The
[validation](../validation/method.md) describes the procedure, and its
[results](../validation/results.md) show it on two dev kits.

## See also

- [API reference](api.md): the errors as Python exceptions.
- [Protocol, known caveats](../measure/protocol.md#10-known-caveats)
