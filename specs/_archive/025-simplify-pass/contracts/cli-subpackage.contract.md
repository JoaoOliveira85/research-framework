# Contract: `cli/` Subpackage Organisation (B5)

**Owner**: Spec 025 US8 B5.
**Status**: pinned at spec 025 plan time (2026-05-21); § 7 amended
2026-09-06 (issues #263, #264) — two of the tests pinned below did not
assert what this table said they did.

Pins the structure of the new `cli/` subpackage that replaces
the monolithic `cli.py`. The goal: `cli.py` shrinks to < 200
lines while preserving every external import path and the
byte-identical `./vault --help` output.

---

## § 1 — Package layout

```text
src/research_framework/
├── cli.py                  # POST-B5: 1-line re-export
└── cli/                    # NEW package
    ├── __init__.py         # build_parser() lives here
    ├── _common.py          # shared subparser helpers
    ├── research.py         # `./vault research`, `--resume`
    ├── audit.py            # `./vault audit`
    ├── vault.py            # `./vault write`, `update`, `onboard`, `install`
    ├── quality.py          # `./vault quality-baseline-update` (spec 022)
    └── doctor.py           # `./vault doctor` (if it exists; otherwise drop)
```

Per-group module count target: **5–8** modules. Each module ≤ 250
lines. `cli/__init__.py` ≤ 50 lines (the aggregator).

Old `cli.py` post-B5:

```python
# src/research_framework/cli.py
"""Backwards-compat shim — the CLI lives in research_framework.cli (package)."""

from research_framework.cli import build_parser, main  # re-export

__all__ = ["build_parser", "main"]
```

Approximate 5 LOC. Required because some downstream importers
use `from research_framework.cli import ...` (the file-level
import) which Python's import system resolves to the package
`__init__.py` when both exist — but the explicit re-export
documents intent.

**Note on file/package collision**: Python resolves
`from research_framework.cli import X` by checking for a package
(`cli/__init__.py`) FIRST, then a module (`cli.py`). Having both
is unusual but legal. The recommended cleanup at the end of B5
is to DELETE `cli.py` entirely once test coverage confirms
nothing imports from the file as opposed to the package. Until
that confirmation, keep the shim.

---

## § 2 — Public API (preserved)

```python
# cli/__init__.py — the public face

import argparse

def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level CLI argument parser.

    Public — imported by external scripts (install.sh, CI, tests).
    Byte-identical --help output pre/post B5 (SC-009).
    """
    parser = argparse.ArgumentParser(
        prog="research-framework",
        description="Research framework CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    from . import research, audit, vault, quality
    for module in (research, audit, vault, quality):
        module.register(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Parse args, dispatch to the appropriate handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # The dispatch table: each command's handler is on the module
    # registered in build_parser. We look it up via the `command`
    # attribute on the parsed namespace.
    handler = _DISPATCH[args.command]
    return handler(args)


_DISPATCH = {
    "research": lambda args: __import__(
        "research_framework.cli.research", fromlist=["handle"]
    ).handle(args),
    "audit":    lambda args: __import__(
        "research_framework.cli.audit",    fromlist=["handle"]
    ).handle(args),
    "vault":    lambda args: __import__(
        "research_framework.cli.vault",    fromlist=["handle"]
    ).handle(args),
    "quality":  lambda args: __import__(
        "research_framework.cli.quality",  fromlist=["handle"]
    ).handle(args),
}
```

Each `cli/<group>.py` exposes a 2-function contract:

```python
# cli/<group>.py

def register(subparsers: argparse._SubParsersAction) -> None:
    """Add this group's subparser(s) to the top-level parser.

    Argparse mutation; no return value.
    """


def handle(args: argparse.Namespace) -> int:
    """Execute the chosen subcommand. Return exit code.

    Reads args.command (set by argparse from `dest="command"`)
    and args.subcommand (if the group has sub-subcommands).
    """
```

---

## § 3 — Behaviour preservation (FR-011 + SC-005 + SC-009)

| Invariant | Verification |
|-----------|--------------|
| `cli.py` ≤ 200 lines | `wc -l src/research_framework/cli.py` post-B5. |
| `cli/__init__.py` ≤ 50 lines | Same. |
| Each `cli/<group>.py` ≤ 250 lines | `find cli/ -name '*.py' -exec wc -l {} +`. |
| `from research_framework.cli import build_parser` resolves to the same callable | Existing test sweep imports it; if the test sweep is green, this passes. |
| `./vault --help` byte-identical pre-/post-B5 | Golden file at `tests/cli/fixtures/help_output_pre_b5.txt`; test diffs against `subprocess.run(["./vault", "--help"]).stdout`. |
| `./vault <command> --help` byte-identical for every command | Parametrised golden-file test. |
| `build_parser()` returns the same `ArgumentParser` topology | `argparse.ArgumentParser._actions` list equality (sufficient for our use). |
| `main(argv)` exit code identical for every argv pre-/post- | Subset of existing CLI tests; if green, passes. |

The golden-file approach is the strongest validation; if `--help`
output diverges by a single character, the test fails and the
implementer knows immediately.

---

## § 4 — Subcommand-level organisation

`cli/research.py` (US4 A4 touches here):

```python
def register(subparsers):
    p = subparsers.add_parser("research", help="Run research cycles.")
    p.add_argument("--cycle", type=int, default=None,
                   help="Resume specific cycle number")
    p.add_argument("--resume", action="store_true",
                   help="Resume in-progress cycle (auto-detect)")
    # ... other existing flags ...
    p.set_defaults(_dispatch=handle)


def handle(args) -> int:
    if args.resume:
        cycle_num = _resolve_resume_cycle(args)  # US4 A4 logic
    else:
        cycle_num = args.cycle or _next_cycle()
    return _run_research(cycle_num, args)


def _resolve_resume_cycle(args) -> int:
    """Auto-detect in-progress cycle from _pipeline/state.json.

    Per spec 025 US4 A4. Raises clear errors on:
      - no in-progress cycle found
      - multiple in-progress cycles
      - corrupted state.json
    """
    # ... implementation ...
```

`cli/audit.py`, `cli/vault.py`, `cli/quality.py` follow the same
pattern with their own subparsers and handlers.

`cli/_common.py` exposes shared helpers:

```python
def add_dry_run_flag(parser): ...
def add_verbose_flag(parser): ...
def resolve_vault_dir(args) -> Path: ...
def confirm_destructive(prompt: str, *, default: bool = False) -> bool: ...
```

These helpers exist pre-B5 but are scattered; B5 consolidates
them.

---

## § 5 — Order of subcommand registration

The `--help` output's subcommand order is **alphabetical by
command name** in the post-B5 implementation. Pre-B5, the order
is whatever order the manual `subparsers.add_parser` calls run
in (which has drifted over time and may not be alphabetical).

**SC-009 byte-identical handling**: if the pre-B5 order is NOT
alphabetical, the SC-009 test fails. The implementer has two
options:
1. Match the pre-B5 order (compute the existing order at start
   of B5, hard-code it in `build_parser`'s iteration). Preserves
   byte-identical output.
2. Switch to alphabetical AND update the golden file. Acceptable
   per SC-009's intent (which is "no behaviour regression"; help
   text order is cosmetic) but requires reviewer signoff.

**Recommendation**: Option 1 (preserve order). Cleanup to
alphabetical is a follow-up cosmetic change.

---

## § 6 — Forward-compat with future commands

Spec 022 adds `./vault quality-baseline-update` (handled by
`cli/quality.py`). Spec 020 (future) may add `./vault module-*`
commands (handled by `cli/vault.py` or a new `cli/module.py`).
Adding a new command post-B5:

1. Create or extend the appropriate `cli/<group>.py`.
2. Add `register(subparsers)` and `handle(args)` if creating a
   new module.
3. Import the module in `cli/__init__.py::build_parser`'s for
   loop.
4. Add to `_DISPATCH` table.
5. Update the golden file at
   `tests/cli/fixtures/help_output_pre_b5.txt` (or create
   `help_output_post_NN.txt` for the new spec NN).

Total per-command-add cost: < 30 minutes. Pre-B5, this cost was
~2 hours because of the cli.py monolith's navigation overhead.

---

## § 7 — Test coverage

| Test | Assertion |
|------|-----------|
| `tests/cli/test_build_parser_stable.py::test_help_byte_identical` | Golden-file diff for `./vault --help`. |
| `tests/cli/test_build_parser_stable.py::test_subcommand_help_byte_identical` | Parametrised golden-file for each subcommand's `--help`, over `generate` / `acceptance` / `cycle` / `digest` (`tests/cli/fixtures/help_<verb>.txt`). T076 named `research` / `audit` / `vault` / `quality` — those are `cli/` module names, not verbs, so the `_pre_025` goldens generated from them held argparse *invalid-choice errors* and pinned no verb's help at all (issue #264). |
| `tests/cli/test_build_parser_stable.py::test_subcommand_golden_pins_help_and_not_an_argparse_error` | Each golden is help output for the verb it is named for — not a rejection. Stops #264 recurring the next time a golden is regenerated from a typo. |
| `tests/cli/test_build_parser_stable.py::test_argparse_topology_unchanged` | `len(parser._actions)` and subparser counts match pre-B5 snapshot. |
| `tests/cli/test_build_parser_stable.py::test_external_import_path` | `from research_framework.cli import build_parser` works (smoke test). |
| `tests/cli/test_build_parser_stable.py::test_parsed_namespace_carries_a_callable_handler` | Parsing each verb's minimal argv yields a namespace whose `func` is callable — the object `main` reads. Replaces `test_main_dispatch_table_complete` (issue #263), whose assertion `getattr(action, "func", None) is not None or action.dest is not None` could never fail. |

Plus existing CLI tests in `tests/cli/test_*.py` continue to
pass unchanged (the strongest behaviour-preservation proof). All
new tests tier-2 per ADR-0008 (golden-file I/O + subprocess
spawning; not pure-function tier-1).
