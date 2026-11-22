"""The documentation must not drift from the code it describes.

On every page: the Python names and the command options it mentions
exist. Where a mistake would cost a reader most: the option tables and
their defaults, the command bytes, the error lines quoted for
troubleshooting, and the examples that need only the stored fixtures,
which must print what the page shows.
"""

import ast
import contextlib
import importlib
import io
import re
from itertools import pairwise
from pathlib import Path

import pytest
from typer.testing import CliRunner

import ppk2
from ppk2 import (
    DEFAULT_SPIKE_FILTER_ALPHA,
    DEFAULT_SPIKE_FILTER_ALPHA5,
    DEFAULT_SPIKE_FILTER_SAMPLES,
    Ambiguous,
    DataPortNotFound,
    HandshakeFailed,
    Mode,
    NotFound,
    Opcode,
    current_micro_amps,
    parse_metadata,
)
from ppk2.cli.main import app

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = [
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "llms.txt",
    ROOT / ".claude/skills/ppk2/SKILL.md",
    *sorted(DOCS.rglob("*.md")),
]
COMMANDS = ("version", "discover", "list", "metadata", "power", "capture", "convert", "run")

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)
_OPTION = re.compile(r"(?<![\w-])(--[a-z][a-z-]+|-[a-z])(?![\w-])")
_INVOCATION = re.compile(r"\bppk2 (" + "|".join(COMMANDS) + r")\b([^\n`|]*)")
_DOTTED = re.compile(r"(?<![\w.])ppk2(?:\.[A-Za-z_]\w*)+")
_MEMBER = re.compile(
    r"\b(Session|Sample|RawSample|StreamParser|SpikeFilter|CalibrationCoefficients|Mode|Opcode)"
    r"\.([A-Za-z_]\w*)"
)
# A wide, colourless terminal: one line of help per option, whatever CI sets.
_PLAIN = {
    "COLUMNS": "400",
    "NO_COLOR": "1",
    "TERM": "dumb",
    "CI": None,
    "GITHUB_ACTIONS": None,
    "FORCE_COLOR": None,
    "CLICOLOR_FORCE": None,
}


def _name(page: Path) -> str:
    return str(page.relative_to(ROOT))


@pytest.fixture(scope="module")
def helps() -> dict[str, str]:
    """The ``--help`` text of every command."""
    runner = CliRunner()
    return {cmd: runner.invoke(app, [cmd, "--help"], env=_PLAIN).output for cmd in COMMANDS}


def _options(help_text: str) -> set[str]:
    return set(_OPTION.findall(help_text)) - {"--help"}


def _default(help_text: str, option: str) -> str:
    """What the help says of ``option``: ``required``, its default, or ``none``."""
    line = next(ln for ln in help_text.splitlines() if ln.lstrip(" │*").startswith(option))
    if "[required]" in line:
        return "required"
    found = re.search(r"\[default: ([^\]]+)\]", line)
    return found.group(1) if found else "none"


# ─── names ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=_name)
def test_python_names_on_the_page_exist(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    for dotted in sorted(set(_DOTTED.findall(text))):
        obj: object = ppk2
        parts = dotted.split(".")
        for depth, part in enumerate(parts[1:], start=2):
            # An attribute of what we have, or else a submodule: both must exist.
            obj = getattr(obj, part, None) or importlib.import_module(".".join(parts[:depth]))
    for cls, member in sorted(set(_MEMBER.findall(text))):
        assert hasattr(getattr(ppk2, cls), member), (
            f"{cls}.{member} is on the page, not in the code"
        )


@pytest.mark.parametrize("page", PAGES, ids=_name)
def test_python_examples_on_the_page_parse(page: Path) -> None:
    """A wrong indent in an example is a SyntaxError for whoever copies it."""
    text = page.read_text(encoding="utf-8")
    for match in re.finditer(r"^( *)```python\n(.*?)^ *```", text, flags=re.S | re.M):
        indent, code = match.groups()
        code = "\n".join(line[len(indent) :] for line in code.splitlines())
        try:
            ast.parse(code)
        except SyntaxError as error:
            line = text.count("\n", 0, match.start()) + 1 + (error.lineno or 0)
            raise AssertionError(f"{_name(page)}:{line}: {error.msg}") from None


# ─── the command line ────────────────────────────────────────────────────


@pytest.mark.parametrize("page", PAGES, ids=_name)
def test_options_used_on_the_page_exist(page: Path, helps: dict[str, str]) -> None:
    for command, rest in _INVOCATION.findall(page.read_text(encoding="utf-8")):
        # Stop at the child command of `ppk2 run -- ...` and at a comment.
        used = rest.split(" -- ")[0].split("#")[0]
        unknown = set(_OPTION.findall(used)) - _options(helps[command]) - {"--help"}
        assert not unknown, f"`ppk2 {command}` has no {sorted(unknown)}"


def test_shared_options_table_names_the_right_commands(helps: dict[str, str]) -> None:
    text = (DOCS / "user/command.md").read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| `(--[a-z-]+)[^`]*` \| [^|]+ \| ((?:`\w+`(?:, )?)+) \|", text)
    assert [option for option, _ in rows] == ["--serial", "--port", "--vdd", "--source"]
    for option, accepted in rows:
        listed = set(re.findall(r"`(\w+)`", accepted))
        having = {cmd for cmd, text_ in helps.items() if option in _options(text_)}
        assert listed == having, f"{option}: the page says {sorted(listed)}"


def test_option_defaults_in_the_tables_are_the_real_ones(helps: dict[str, str]) -> None:
    text = (DOCS / "user/command.md").read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| `(--[a-z-]+)[^|]*\| ([^|]+?) \|", text)
    assert len(rows) >= 7
    for option, cell in rows:
        command = next(cmd for cmd in COMMANDS if option in _options(helps[cmd]))
        real = _default(helps[command], option)
        if cell in ("none", "off", "required"):
            assert real == ("required" if cell == "required" else "none"), option
        else:
            assert float(cell) == float(real), option


# ─── the protocol ────────────────────────────────────────────────────────


def test_command_table_matches_opcode() -> None:
    text = (DOCS / "measure/protocol.md").read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\| `(0x[0-9A-Fa-f]{2})` \| `([A-Z_]+)` \|", text)
    assert len(rows) >= 11
    for byte, name in rows:
        assert Opcode[name] == int(byte, 16), name
    modes = dict(re.findall(r"(?m)^\| (Ampere meter|Source meter) \| `(0x0[12])` \|", text))
    assert int(modes["Ampere meter"], 16) == Mode.AMPERE
    assert int(modes["Source meter"], 16) == Mode.SOURCE


def test_spike_filter_defaults_on_the_page() -> None:
    text = (DOCS / "measure/principle.md").read_text(encoding="utf-8")
    for name, value in (
        ("samples", DEFAULT_SPIKE_FILTER_SAMPLES),
        ("alpha", DEFAULT_SPIKE_FILTER_ALPHA),
        ("alpha5", DEFAULT_SPIKE_FILTER_ALPHA5),
    ):
        assert re.search(rf"\| `{name}` \| {value:g} \|", text), name


def test_worked_calibration_example_is_what_the_formula_gives() -> None:
    coeffs = parse_metadata((ROOT / "tests/fixtures/metadata.raw").read_bytes())
    text = (DOCS / "measure/principle.md").read_text(encoding="utf-8")
    assert f"uA = {current_micro_amps(151, 0, 3300, coeffs)!r}" in text


def test_plots_on_the_site_are_the_ones_the_script_wrote() -> None:
    plots = ROOT / "validation/evidence/bench_dut/plots"
    for copy, source in (
        ("parity_ampere.png", "ampere_parity.png"),
        ("parity_source.png", "source_parity.png"),
        ("wakeup.png", "wakeup.png"),
    ):
        assert (DOCS / "img" / copy).read_bytes() == (plots / source).read_bytes(), copy


# ─── error lines ─────────────────────────────────────────────────────────


def test_error_lines_quoted_for_troubleshooting_are_the_real_ones() -> None:
    page = (DOCS / "user/troubleshooting.md").read_text(encoding="utf-8")
    assert str(NotFound()) in page
    assert str(DataPortNotFound(("a",))).split(":")[0] in page
    assert str(Ambiguous(2)) in page
    assert str(HandshakeFailed(3, "x")).split(";")[0] in page

    cli = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "src/ppk2/cli").rglob("*.py"))
    for literal in (
        "no samples captured: check the PPK2 mode and the DUT's power",
        "close the nRF Connect Power Profiler, or whatever else holds the port",
        "[busy: held by another process?]",
    ):
        assert literal in page, literal
        assert literal in cli, literal


# ─── examples ────────────────────────────────────────────────────────────


def _fixture_examples() -> list[tuple[str, str, str]]:
    """Python examples that read only ``tests/fixtures``, each with the output shown under it."""
    found: list[tuple[str, str, str]] = []
    for page in PAGES:
        blocks: list[tuple[str, str]] = _FENCE.findall(page.read_text(encoding="utf-8"))
        for (lang, code), (next_lang, shown) in pairwise(blocks):
            if lang == "python" and "tests/fixtures" in code and next_lang == "text":
                found.append((_name(page), code, shown))
    return found


def test_there_are_fixture_examples_to_run() -> None:
    assert len(_fixture_examples()) >= 3


@pytest.mark.parametrize(
    ("page", "code", "shown"), _fixture_examples(), ids=[e[0] for e in _fixture_examples()]
)
def test_fixture_example_prints_what_the_page_shows(
    page: str, code: str, shown: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(code, page, "exec"), {"__name__": "__main__"})
    assert printed.getvalue() == shown
