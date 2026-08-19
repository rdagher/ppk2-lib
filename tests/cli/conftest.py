"""Make CLI help rendering deterministic across environments.

rich (via typer) force-enables ANSI colour and box-drawing when it
detects a CI environment (``GITHUB_ACTIONS``/``CI``), which splices
escape codes mid-token and breaks the plain-substring assertions
these tests make against ``--help`` output. Scrub the detection
variables and pin a wide plain terminal so the output is identical
locally and on any CI.
"""

import pytest


@pytest.fixture(autouse=True)
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITHUB_ACTIONS", "CI", "FORCE_COLOR", "CLICOLOR_FORCE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("COLUMNS", "200")
