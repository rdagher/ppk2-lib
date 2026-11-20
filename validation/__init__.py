"""Validation harness: port-agnostic comparators and capture orchestration.

Run as Python modules so relative imports between the scripts work:

    uv run --group validation python -m validation.compare_cli A.csv B.csv
    uv run --group validation python -m validation.cross_validate --binary-a … --binary-b …
"""
