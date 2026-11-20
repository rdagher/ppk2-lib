# ppk2-lib: task runner.
#
# `just <recipe>`; `just --list` enumerates. Recipes wrap uv,
# pytest, ruff, pyright, and the validation harness.

# Show available recipes.
_default:
    @just --list --unsorted

# ─── Setup ──────────────────────────────────────────────────────

# Install runtime + dev deps into .venv.
sync:
    uv sync

# ─── Fast tier (no hardware) ────────────────────────────────────

# Pytest, excluding the hardware-marked HIL tests.
test:
    uv run pytest -m 'not hardware'

# Pyright (strict) + ruff lint + ruff format-check.
check:
    uv run pyright src tests
    uv run ruff check src tests validation
    uv run ruff format --check src tests validation

# Apply ruff format to src + tests + validation.
fmt:
    uv run ruff format src tests validation

# CI fast tier: static analysis + fast tests.
ci: check test

# ─── HIL tier (bench machine, PPK2 plugged in) ─────────────────

# Run the @pytest.mark.hardware tests (real PPK2 + bench DUT required).
# Ampere meter mode by default; PPK2_HIL_SOURCE_MV=3300 for Source meter mode.
test-hw:
    uv run pytest -m hardware -s

# Two-tier CI: fast tier + HIL tier.
ci-hil: ci test-hw

# ─── Validation (port-agnostic A/B captures) ───────────────────

# Redraw the validation plots from the stored captures (no hardware).
# `git status` is clean afterwards if the plots are up to date.
plots:
    uv run --group validation python validation/evidence/trace_demo/make_plots.py

# Compare two CSV captures and write a Markdown report (no hardware).
compare-cli a b:
    uv run --group validation python -m validation.compare_cli {{a}} {{b}}

# Capture from two ppk2-compatible binaries back-to-back and compare (HIL).
cross-validate binary_a binary_b seconds="60":
    uv run --group validation python -m validation.cross_validate \
        --binary-a {{binary_a}} --binary-b {{binary_b}} \
        --seconds {{seconds}}

# ─── Convenience ────────────────────────────────────────────────

# Build wheels + sdist into ./dist/.
build:
    uv build

# Build the documentation site into ./site/.
docs:
    uv run --group docs zensical build --clean

# Preview the documentation site on localhost:8000.
docs-serve:
    uv run --group docs zensical serve

# Wipe build / cache artefacts (keep .venv).
clean:
    rm -rf build/ dist/ site/ .pytest_cache/ .ruff_cache/ .pyright/
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
