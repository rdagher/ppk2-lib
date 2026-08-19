"""Smoke tests verifying the package skeleton is importable."""

import ppk2


def test_version_is_set() -> None:
    assert ppk2.__version__ == "0.1.0"
