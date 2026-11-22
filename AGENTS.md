# For coding agents

Read [CONTRIBUTING.md](CONTRIBUTING.md) before editing code or
documentation. It has the checks to run and the rule book of the
documentation: where each kind of text goes, Nordic's wording, numbers
and units, and what `tests/test_docs.py` verifies.

- `just ci` must pass: type check, lint, unit tests, pages against the
  code.
- `just docs` must pass: the site builds with no broken internal link.
- `just test-hw` needs a PPK2 and the bench of `tests/hil/README.md`.
  Do not run it unless asked.
- Every example in the documentation is run as printed before it is
  committed, and its output is the real one.
- The captures of the validation are on the branch `captures`, not on
  `main`. `just captures` puts them in
  `validation/evidence/bench_dut/captures/`, where git ignores them.
- [.claude/skills/ppk2/SKILL.md](.claude/skills/ppk2/SKILL.md) is the
  procedure for driving a PPK2 with this package.
- [llms.txt](llms.txt) is the map of the documentation.
