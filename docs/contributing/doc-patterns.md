# Doc patterns

For anyone who edits this documentation.

## Three purposes

The documentation exists for three things, and has one part for each.
A page that serves none of them does not belong.

| Purpose | The reader asks | Part |
|---|---|---|
| The user | How do I capture, from a terminal, a script or CI? | Using it |
| The measurement protocol and principle | What exactly is measured, and how does one talk to a PPK2? | How it measures |
| Cross-validation against Nordic's app | Why believe the numbers? | Validation against Nordic's app |

Keep the parts in proportion. The user part should be short enough to
read at a bench. The validation part is what the package's claim rests
on: it gets the method and the results in full, with the numbers.

## Three homes

Each piece of documentation has one natural home. In the wrong one it
drifts away from the code, or sits where readers do not look.

| Kind | Home | Reader |
|---|---|---|
| API reference: what a function takes, returns and raises | Docstrings in `src/ppk2/`, rendered into the API reference page | Someone using the library |
| User manual: how to capture, recipes, troubleshooting | The pages under `docs/use/` | Anyone using the tool |
| Why and evidence: decisions, measurements, what was tried | The protocol page's known caveats, the validation pages, commit messages | Contributors and maintainers |

To decide:

- "What does this function take?" goes in the docstring.
- "How do I capture for an hour?" goes in a page.
- "Why this wait, and how do we know?" goes in the known caveats or in
  the commit message.

When in doubt, choose the home closest to the code.

## What goes on which page

| Page | Content |
|---|---|
| Getting started | For someone with a PPK2 who has never run `ppk2 capture`: install, wire, capture, read |
| The `ppk2` command | Every command, option and exit code |
| Recipes | One job per section, concrete, with commands that run |
| Architecture | The layers, the life of a session, the callback, the settings, threads, the choices |
| API reference | A few lines per group, then the docstrings |
| Troubleshooting | One heading per error line |
| Measurement principle | The chain from the DUT's current to the number in the file |
| Protocol | The bytes, and how the PPK2 behaves |
| File formats | The CSV and the `.ppk2` session file |
| Validation: method | What is compared, the bench procedure, the criteria |
| Validation: results | The tables and plots, the differences from the app, the limits |

## One home per fact

A fact is written once. Other places link to it.

| Fact | Home |
|---|---|
| Command bytes | `src/ppk2/protocol/opcode.py`, described on the protocol page |
| Sample layout | `src/ppk2/protocol/sample.py`, drawn on the protocol page |
| Calibration formula | `src/ppk2/protocol/calibration.py`, explained under Measurement principle |
| Stream parsing | `src/ppk2/protocol/stream.py`, described on the protocol page |
| Order of a session | `src/ppk2/client/session.py`, drawn under Architecture and Protocol |
| CSV and `.ppk2` formats | `src/ppk2/cli/`, described under File formats |
| What the PPK2 was seen to do | Known caveats on the protocol page |
| A number of the validation | The script that prints it, then the results page |

If the code changes and a page disagrees, the page is wrong.

## Words

Use Nordic's words for what Nordic already names. A reader comes from
the Power Profiler app and its user guide.

| Write | Not |
|---|---|
| Ampere meter mode, Source meter mode | ammeter, source mode |
| DUT, spelled out once per page as device under test | board, target |
| digital inputs, on the logic port | logic inputs, logic pins |
| the app, the Power Profiler app | the GUI |
| supply voltage | output voltage, setpoint |
| Enable power output, Samples to smooth, Save / Export | another name for an app control |

A dev kit is a dev kit when the page is about that particular kit.

The app numbers the measurement ranges 1 to 5 and the stream numbers
them 0 to 4. Say which one a number is, every time.

## Style

Write for a reader who is at a bench with a PPK2 and wants to get
something done.

- Start a page with what the thing is or what the reader wants.
- Give numbers with their units, and say on what they were measured.
- State limits plainly. "Not tried on Windows" is more useful than
  silence.
- Prefer "is", "has" and "use" to longer words. Keep sentences short.
- One name per thing, sentence-case headings, plain punctuation.
- Use a list for parallel items and a table for things with the same
  attributes. Use sentences for everything else.

## Examples and output

- Every command and every Python example is run before it is
  published. The examples on this site ran against the bench firmware
  in `tests/hil/bench-dut`, in Source meter mode. Where a page shows
  `Mode.AMPERE`, that one line was changed for the run.
- Output shown under a command is real output. If you describe the
  form of a message instead, use placeholders such as `<count>`.
- Use fenced blocks with a language: `sh`, `console` for a command with
  its output, `python`, `text`, `csv`.

## Docstrings

The library pages render the docstrings, so they must read well there
too.

- Google style: `Args:`, `Returns:`, `Raises:`.
- The first sentence says what the function does. It becomes the
  summary.
- Do not repeat the signature in prose. It is rendered above the text.
- No file and line references to Nordic's source, and no dates. They go
  stale, and they read as private notes once rendered.

## Pages

- Notes and warnings (`!!! note`) are for the one thing a reader must
  not miss on a page. Most pages need none.
- Diagrams are Mermaid, in a fenced block. Sequence, state and
  flowchart diagrams render everywhere. The `packet` diagrams of the
  protocol page are newer, so each has a table below it with the same
  content.
- Links between pages are relative: `../measure/principle.md`.
- To link to a function, use its full name as the anchor:
  `api.md#ppk2.client.session.Session.capture`.

## Reference blocks

In a library page the narrative comes first and the reference below
it, from the docstrings:

```markdown
::: ppk2.protocol.metadata.parse_metadata
```

For a class with many methods, list the ones to show:

```markdown
::: ppk2.client.session.Session
    options:
      members:
        - open
        - capture
```

## Numbers and units

- A space between a number and its unit, the percent sign included:
  `13.5 %`, `0.2 µA`. This is the SI convention (NIST SP 811, 7.2 and
  7.10.2). The exceptions are quotations, such as the app's `200nA`,
  and `Current(uA)` in code font.
- A range is written `0.8 to 5.0 V`.
- Digits are grouped with a comma from four digits on: `301,056`
  samples, `2,244.7 µC`. SP 811 advises a space instead; the comma is
  the choice here, used everywhere.
- A `±` says what it is the first time it appears on a page, for
  instance "mean ± standard deviation over the 31 regions". Give the
  spread to two significant digits and round the value to the same
  place (GUM, JCGM 100:2008, 7.2).
- A difference in percent says what is compared with what, and which
  one is the reference.
- Charge, not energy. A PPK2 measures current, so what a capture gives
  is a charge in µC. An energy needs a voltage the capture does not
  contain. Say so where a reader might expect joules.

## Watch for

- The order of the digital inputs. In the CSV's `D0-D7` field, D0 is
  the leftmost character. In `Sample.logic`, D0 is bit 0. Say which one
  you mean.
- Units: µA, mV, µC, ms. The CSV column is `Current(uA)`. See
  [numbers and units](#numbers-and-units).
- `Calibrated: false`. Link to its section of the measurement
  principle the first time it appears on a page. It is the line readers
  most often take for a fault.
- The names: the distribution is `ppk2-lib`, the package and the
  command are `ppk2`.
- Dates and measurement details. They belong in the known caveats, on
  the validation pages and in commit messages. Everywhere else, state
  the fact.
- Numbers of the validation. Quote only what a script in the
  repository prints from the stored evidence, and say which script.

## Checked against the code

`tests/test_docs.py` runs with the unit tests and fails when a page and
the code disagree on:

- a Python name, or an option of a `ppk2` command, anywhere on a page;
- the option tables of the command page, with their defaults;
- the command and mode bytes of the protocol page;
- the defaults of the spike filter and the worked calibration example;
- the error lines quoted under troubleshooting;
- the output shown under an example that reads only `tests/fixtures`.

So when a default, a message or a name changes in the code, the test
says which page to update. It cannot check prose: a sentence about what
the code does still has to be read against the code.

## Build and preview

```sh
just docs          # build into site/
just docs-serve    # preview on http://localhost:8000
```

The site is built with [Zensical](https://zensical.org), which reads
`mkdocs.yml` at the root of the repository.
