# ppk2-lib

A Python library and command-line tool for Nordic's Power Profiler
Kit II (PPK2). The PPK2 measures the current of a device under test
(DUT) and samples eight digital inputs with it, 100,000 times per
second. With ppk2-lib a script, a terminal or a CI job drives it,
without the Power Profiler app.

This is an experimental release (0.1.0). It works and is checked on
hardware, but the API may still change between 0.x versions.

## Three parts

This documentation answers three questions.

| Question | Part | Pages |
|---|---|---|
| How do I use it? | Using it | [Getting started](use/getting-started.md), [the `ppk2` command](use/command.md), [recipes](use/recipes.md), [architecture](use/architecture.md), [API reference](use/api.md), [troubleshooting](use/troubleshooting.md) |
| What exactly is measured, and how does one talk to a PPK2? | How it measures | [Measurement principle](measure/principle.md), [protocol](measure/protocol.md), [file formats](measure/formats.md) |
| Why believe the numbers? | Validation against Nordic's app | [Method](validation/method.md), [results](validation/results.md) |

If this is your first time, start with
[getting started](use/getting-started.md).

## What it is good for

- Sleep and idle currents. The lowest of the PPK2's five measurement
  ranges resolves 0.2 µA.
- Comparing two firmware builds: capture the same workload before and
  after a change and compare the files.
- The charge one piece of code draws: raise a GPIO around it and add up
  the current while the pin is high.
- Powering a DUT from a script, for instance while it is flashed.
- Captures in the app's own formats: `ppk2` writes the CSV the app
  exports and its `.ppk2` session file.

The [recipes](use/recipes.md) show each of these.

## What it is not for

- Edges shorter than 10 µs. One sample lasts 10 µs.
- Accuracy beyond the PPK2's own. Nordic gives it as better than
  ±20 %, and ppk2-lib is checked against Nordic's app, not against a
  calibrated instrument.
- Voltage. The PPK2 measures current only.
- Looking around a trace by eye. The app's chart is the better tool:
  save a `.ppk2` file and open it there.

## Names

| What | Name |
|---|---|
| Distribution, what you install | `ppk2-lib` |
| Python package, what you import | `ppk2` |
| Command | `ppk2` |

The distribution has its own name because `ppk2-api` on PyPI is
another project, IRNAS's library.
