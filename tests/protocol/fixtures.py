"""Shared fixture paths for protocol tests.

All fixtures live in-repo at ``tests/fixtures/`` — the test suite has no
dependencies outside this repository. See ``tests/fixtures/README.md``
for provenance.
"""

from pathlib import Path

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

METADATA_RAW: Path = _FIXTURES / "metadata.raw"
METADATA_PARSED_JSON: Path = _FIXTURES / "metadata.parsed.json"
STREAM_BIN: Path = _FIXTURES / "stream_4000.bin"
PARSED_CSV: Path = _FIXTURES / "parsed_1000.csv"
