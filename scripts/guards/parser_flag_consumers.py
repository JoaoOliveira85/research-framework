#!/usr/bin/env python3
"""Guard: every parser flag must reach a non-CLI consumer (issue #271).

Six accepted-but-inert options have been found in this repo — ``url:``,
``--target-topics`` (spec 074), ``source_policy: hard``, ``pipeline
--budget-cap`` (#232), ``vault.corpus_dir`` (#251), and, until PR #210,
``verify``'s ``auto_fix`` / ``fail_threshold``. The 1.1.0 CHANGELOG names the
pattern four times. Six point fixes and four changelog paragraphs is the
argument for an invariant instead.

**What it checks.** Every optional flag on every subparser of
``research_framework.cli.build_parser`` must satisfy both:

1. its ``dest`` is *read* somewhere under ``src/research_framework/cli/``
   (``args.x``, ``getattr(args, "x")``, ``_flag_is_true(args, "x")``); and
2. its ``dest`` appears as a real Python identifier — not prose, not a string
   literal — in at least one module OUTSIDE ``cli/``, i.e. the value crosses
   the CLI boundary into something that does work with it.

Rule 2 is waivable through :data:`ALLOWLIST`, one entry per flag with a
reason. Rule 1 is not waivable by anything: a flag nobody reads at all is the
#232 bug in its purest form and no reason string redeems it.

**What it does NOT check, said plainly.** A flag whose value is threaded into
a non-CLI function that then ignores it still passes — that was the shape of
both ``--target-topics`` and ``--budget-cap``, and catching it needs real
dataflow analysis, not a name scan. This guard closes the *cheapest* half of
the class: the flag that never leaves ``cli/`` at all. Read it as a floor.

**Fail-closed (#217, #278).** A guard whose scan root can go empty passes
vacuously. Everything here is reported as counts —
:class:`FlagConsumptionReport` carries the discovered flags and the scanned
consumer files — and ``tests/cli/test_parser_flag_consumer_guard.py`` asserts
floors on both before it asserts the invariant.

**Why a runtime walk, not an AST walk.** ``_parser.py`` builds every flag with
literal ``add_argument`` calls today, so an AST walk would work today. It
would also have to re-implement argparse's ``dest`` inference (``--max-usd`` →
``max_usd``), its ``dest=`` overrides and its subparser nesting, and would go
quietly blind the first time a flag is added in a loop or by a shared helper.
Asking the built parser what it parses cannot drift from what it parses.

Usage:
    python scripts/guards/parser_flag_consumers.py [--list]
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "research_framework"
_CLI_ROOT = _SRC_ROOT / "cli"
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"

#: Flags that legitimately never leave ``cli/``, keyed ``"<subcommand> <dest>"``
#: (``"(root) <dest>"`` for a top-level flag). Every value is a reason, and
#: ``test_no_allowlist_entry_is_stale`` deletes the entry for you — by going
#: red — the moment the flag gains a consumer or disappears.
#:
#: Every entry below is a *control-flow* flag: ``cli/`` branches on it and
#: calls different non-CLI code either way. The value itself has nothing to
#: cross the boundary, so requiring it to would only invite a decorative
#: parameter nobody reads.
ALLOWLIST: dict[str, str] = {
    "(root) log_level": (
        "presentation-only: cli/__init__.py hands it to logging.basicConfig "
        "before any subcommand runs; no pipeline module takes a log level."
    ),
    "digest last_week": (
        "control flow: cli/digest.py resolves it to a concrete since/until "
        "date pair, and it is that pair — not the flag — that is passed on."
    ),
    "digest last_month": (
        "control flow: as --last-week, resolved to a date pair in cli/digest.py."
    ),
    "digest last_quarter": (
        "control flow: as --last-week, resolved to a date pair in cli/digest.py."
    ),
    "generate approve_all": (
        "control flow: cli/budget_resume.py decides whether to clear a paused "
        "budget marker; the decision, not the flag, reaches the pipeline."
    ),
    "generate force_budget": (
        "control flow: cli/budget_resume.py uses it to override the budget "
        "refusal before dispatching; nothing downstream needs the flag."
    ),
    "generate legacy_cycle_runner": (
        "control flow: selects which runner cli/research_generate.py and "
        "cli/research_resume.py call. A runtime switch, not a parameter."
    ),
    "generate prepopulate": (
        "control flow: cli/research_generate.py copies the directory into the "
        "new vault's _pipeline/ itself before the pipeline starts."
    ),
    "generate regenerate_plan_only": (
        "control flow: selects the plan-only branch in "
        "cli/research_generate.py, which skips scaffolding and Phase 2/3."
    ),
    "generate skip_gate": (
        "control flow: cli/research_generate.py skips the Phase 1 pytest gate. "
        "A testing escape hatch that exists only at the CLI."
    ),
    "generate approve": (
        "control flow: cli/budget_resume.py compares it against the paused "
        "marker's stage and decides whether to clear the marker. The decision "
        "reaches the pipeline; the stage name does not."
    ),
    "generate reject": (
        "control flow: as --approve, cli/budget_resume.py acts on it and then "
        "stops the run; nothing downstream ever sees it."
    ),
    "generate more_cycles": (
        "resolved, not passed: cli/_budget_resolve.py folds it into the "
        "cycle ceiling (`max_cycles = start_cycle + N - 1`) before anything "
        "downstream is called, and it is that ceiling — read by "
        "pipeline/orchestrator.py — that crosses the boundary. Same shape as "
        "--last-week's date pair. A `more_cycles` field beside the resolved "
        "ceiling would be a second copy nobody reads (issue #239)."
    ),
    "generate estimate_only": (
        "control flow: selects the preflight branch in "
        "cli/research_generate.py, which calls "
        "pipeline/budget_preflight.estimate_cycle and returns without "
        "dispatching. The preflight prices the vault, not the flag (#238)."
    ),
    "cycle estimate_only": (
        "control flow: as generate --estimate-only, the branch in "
        "cli/research_cycles.py that calls pipeline/budget_preflight instead "
        "of run_single_cycle (#238)."
    ),
    "refresh-sources verbose": (
        "presentation-only: cli/refresh_sources.py::_run_collector streams the "
        "collector subprocess's output instead of buffering it. Nothing about "
        "what gets collected changes."
    ),
}


@dataclass(frozen=True)
class ParserFlag:
    """One optional flag on one (sub)parser."""

    subcommand: str
    options: tuple[str, ...]
    dest: str

    @property
    def key(self) -> str:
        return f"{self.subcommand} {self.dest}"

    def __str__(self) -> str:  # pragma: no cover — diagnostics only
        return f"{self.subcommand} {self.options[0]} (dest={self.dest})"


@dataclass
class FlagConsumptionReport:
    """Everything the audit saw, so a caller can assert it saw enough."""

    flags: list[ParserFlag] = field(default_factory=list)
    consumer_files: list[Path] = field(default_factory=list)
    cli_files: list[Path] = field(default_factory=list)
    #: parsed, but never read under cli/ — unwaivable
    unread: list[str] = field(default_factory=list)
    #: read under cli/, never reaches a non-CLI module, not allowlisted
    unconsumed: list[str] = field(default_factory=list)
    #: allowlist keys that no longer describe reality
    stale_allowlist: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def discover_flags() -> list[ParserFlag]:
    """Walk the built parser, descending into every subparser."""
    if str(_REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
    from research_framework.cli import build_parser

    return _walk(build_parser(), "(root)")


def _walk(parser: argparse.ArgumentParser, subcommand: str) -> list[ParserFlag]:
    flags: list[ParserFlag] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                flags.extend(_walk(subparser, name))
            continue
        if not action.option_strings:
            # Positionals are named by the verb's own contract and always
            # consumed by it; the inert-option class is about flags.
            continue
        if action.dest in ("help", argparse.SUPPRESS):
            continue
        flags.append(
            ParserFlag(
                subcommand=subcommand,
                options=tuple(action.option_strings),
                dest=action.dest,
            )
        )
    return flags


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def cli_files() -> list[Path]:
    return _python_files(_CLI_ROOT)


def consumer_files() -> list[Path]:
    """Everything a flag could legitimately reach: the package minus ``cli/``,
    plus the ``scripts/`` tree the CLI shells out to."""
    package = [p for p in _python_files(_SRC_ROOT) if _CLI_ROOT not in p.parents]
    return package + _python_files(_SCRIPTS_ROOT)


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------


class _IdentifierCollector(ast.NodeVisitor):
    """Every name a module actually *uses*, ignoring prose.

    Comments, docstrings and string literals are excluded by construction —
    they are not nodes with identifiers. That matters: ``--budget-cap`` was
    described as "passed to agent invocations" in its own help text for a
    whole release while nothing read it, and a grep-based guard would have
    accepted the sentence as the evidence.
    """

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        self.names.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.names.add(node.attr)
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        if node.arg:
            self.names.add(node.arg)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self.names.add(node.arg)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        self.generic_visit(node)


def identifiers(path: Path) -> set[str]:
    """Identifiers used by one module. Raises ``SyntaxError`` if it won't parse
    — a file this guard cannot read must be loud, not silently un-guarding
    every flag it might have consumed."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    collector = _IdentifierCollector()
    collector.visit(tree)
    return collector.names


def dest_is_referenced(dest: str, files: Iterable[Path]) -> bool:
    return any(dest in identifiers(path) for path in files)


def _read_forms(dest: str) -> tuple[str, ...]:
    """The ways ``cli/`` actually gets a value off the parsed namespace.

    Textual rather than AST-shaped because half of them are string keys
    (``getattr(args, "approve", None)``, ``_flag_is_true(args, "force_budget")``)
    that no identifier walk can see. Anchored on ``args`` so a bare mention of
    the word in a help string or an error message does not count as a read.
    """
    return (
        f"args.{dest}",
        f'getattr(args, "{dest}"',
        f"getattr(args, '{dest}'",
        f'(args, "{dest}"',
        f"(args, '{dest}'",
    )


def _is_read_in_cli(dest: str, cli_text: str) -> bool:
    """Was the flag read at all? (Rule 1 — unwaivable.)"""
    return any(form in cli_text for form in _read_forms(dest))


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def audit() -> FlagConsumptionReport:
    report = FlagConsumptionReport(
        flags=discover_flags(),
        consumer_files=consumer_files(),
        cli_files=cli_files(),
    )
    cli_text = "\n".join(path.read_text(encoding="utf-8") for path in report.cli_files)
    consumer_names: set[str] = set()
    for path in report.consumer_files:
        consumer_names |= identifiers(path)

    reaches_a_consumer: set[str] = set()
    for flag in report.flags:
        if not _is_read_in_cli(flag.dest, cli_text):
            report.unread.append(flag.key)
        if flag.dest in consumer_names:
            reaches_a_consumer.add(flag.key)
        elif flag.key not in ALLOWLIST:
            report.unconsumed.append(flag.key)

    live_keys = {flag.key for flag in report.flags}
    report.stale_allowlist = sorted(
        key
        for key in ALLOWLIST
        # Gone entirely, or no longer needs the waiver.
        if key not in live_keys or key in reaches_a_consumer
    )
    return report


def format_failure(report: FlagConsumptionReport) -> str:
    lines = [
        f"{len(report.unconsumed)} parser flag(s) never reach a non-CLI "
        f"consumer (scanned {len(report.flags)} flags against "
        f"{len(report.consumer_files)} modules):",
    ]
    by_key = {flag.key: flag for flag in report.flags}
    for key in report.unconsumed:
        lines.append(f"  - {by_key[key]}")
    lines.append(
        "\nEither wire the value into the module that should honour it, or — "
        "if the flag is genuinely CLI-only — add it to ALLOWLIST in "
        "scripts/guards/parser_flag_consumers.py with a reason. A flag that "
        "is neither is the '#232 accepted and ignored' class."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list",
        action="store_true",
        help="print every discovered flag and whether it reaches a consumer",
    )
    args = parser.parse_args(argv)

    report = audit()
    if args.list:
        unconsumed = set(report.unconsumed)
        for flag in sorted(report.flags, key=lambda f: f.key):
            if flag.key in ALLOWLIST:
                mark = "ALLOWLISTED"
            elif flag.key in unconsumed:
                mark = "UNCONSUMED"
            else:
                mark = "ok"
            print(f"{mark:>12}  {flag}")
        return 0

    failed = False
    if report.unread:
        print(
            "[parser-flags] parsed but never read under cli/: "
            + ", ".join(sorted(report.unread)),
            file=sys.stderr,
        )
        failed = True
    if report.unconsumed:
        print("[parser-flags] " + format_failure(report), file=sys.stderr)
        failed = True
    if report.stale_allowlist:
        print(
            "[parser-flags] stale ALLOWLIST entries (the flag is gone, or it "
            "now reaches a consumer — delete them): "
            + ", ".join(report.stale_allowlist),
            file=sys.stderr,
        )
        failed = True
    if failed:
        return 1
    print(
        f"[parser-flags] {len(report.flags)} flags checked against "
        f"{len(report.consumer_files)} modules; all reach a consumer or carry "
        f"a documented reason ({len(ALLOWLIST)} allowlisted)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
