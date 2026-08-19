"""Entry point for ``python -m ppk2``.

Re-uses the wrapped entry point exported by [`ppk2.cli.main`][] so the
top-level error mapping (clean one-line diagnostics, exit codes)
applies identically to both invocation styles.
"""

from ppk2.cli.main import main

main()
