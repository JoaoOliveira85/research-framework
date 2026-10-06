"""Every non-zero return from a CLI verb must have said why (spec 077, #248).

Spec 070 FR6 — "every non-zero exit MUST write a diagnosable message to
stderr" — has been marked DONE since v1.0.0, and the only thing enforcing it
was a *backstop*: `cli.main`'s `_ReasonCounter` notices, after the fact, that a
verb exited non-zero having said nothing, and prints an apology. That is a
smoke alarm, not a building code. It fires once, at runtime, for whoever
happened to run the command — which on this project is a cron job at 03:00
against eight vaults.

This is the building code: a static walk of every `_cmd_*` / `cmd_*` function
under `src/research_framework/cli/`, asserting that each `return <non-zero>`
has a write to stderr on the path to it.

**What "on the path to it" means.** For each non-zero return, the enclosing
statement list is searched for a stderr write before the return; failing that,
the search widens to the enclosing block, and so on out to the function body.
That approximation is deliberate: it catches the shape the incident actually
had — a bare `return 2` inside an `if` with no message anywhere near it —
without pretending to do reachability analysis.

**Why an allowlist rather than a rule with no exceptions.** Not every non-zero
exit is an error. `1` in the 077 model is "fail/terminate — this unit of work
is over, move on", and a verb whose operator answered "no" to a confirmation
prompt is in exactly that state: nothing failed, nothing was done, and the
message belongs on stdout with the rest of the interaction. Each exception
carries its reason here, one line, the same shape
`scripts/guards/parser_flag_consumers.py` uses.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_DIR = _REPO_ROOT / "src" / "research_framework" / "cli"

#: ``(module, function, lineno-independent reason)`` — a non-zero return that
#: deliberately says nothing on stderr. One entry per *function*, because the
#: reason is a property of the verb's contract, not of a line number.
ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "vault.py",
        "_cmd_prune",
    ): (
        "Returns 1 when the operator declines the confirmation prompt (077 "
        "D4/T003). Nothing failed and nothing was done; the message belongs on "
        "stdout with the rest of the interaction."
    ),
    (
        "vault.py",
        "_cmd_regenerate_agents",
    ): (
        "Same as _cmd_prune: 1 for a declined confirmation, message on stdout. "
        "The two verbs disagreed (0 vs 1) until 077 T003 made them agree."
    ),
}

_STDERR_WRITERS = frozenset({"error", "critical", "exception"})


def _writes_to_stderr(node: ast.AST) -> bool:
    """``print(..., file=sys.stderr)``, a logger ``.error``/``.critical``, or a
    raise — the three ways this codebase reports a reason."""
    if isinstance(node, ast.Raise):
        return True
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id == "print":
            for kw in child.keywords:
                if kw.arg == "file" and "stderr" in ast.unparse(kw.value):
                    return True
        if isinstance(func, ast.Attribute) and func.attr in _STDERR_WRITERS:
            return True
        # `_emit_stderr(...)`, `_print_error(...)` and friends.
        if isinstance(func, ast.Name) and "stderr" in func.id:
            return True
    return False


def _nonzero_returns(func: ast.FunctionDef) -> list[ast.Return]:
    out: list[ast.Return] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Return):
            continue
        value = node.value
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, int)
            and not isinstance(value.value, bool)
            and value.value != 0
        ):
            out.append(node)
    return out


def _path_to(
    func: ast.FunctionDef, target: ast.Return
) -> list[tuple[list[ast.stmt], int]]:
    """``(block, index)`` for each statement list on the path to *target*.

    Innermost first. ``index`` is the position, in that block, of the statement
    that leads to the return — the return itself in the innermost block, and
    the enclosing ``if`` / ``try`` / loop further out. Carrying the index is
    what makes "before" mean before: a stderr write that sits AFTER the branch
    the return is in is not on the path to it, and the first draft of this
    guard counted those, which is why it passed on its first run.
    """
    found: list[tuple[list[ast.stmt], int]] = []

    def walk(stmts: list[ast.stmt], trail: list[tuple[list[ast.stmt], int]]) -> bool:
        for index, stmt in enumerate(stmts):
            if stmt is target:
                found.extend([(stmts, index), *reversed(trail)])
                return True
            for field in ("body", "orelse", "finalbody"):
                inner = getattr(stmt, field, None)
                if isinstance(inner, list) and walk(inner, [(stmts, index), *trail]):
                    return True
            for handler in getattr(stmt, "handlers", []) or []:
                if walk(handler.body, [(stmts, index), *trail]):
                    return True
        return False

    walk(func.body, [])
    return found


_BRANCHING = (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.Match)


def _reason_reaches(func: ast.FunctionDef, target: ast.Return) -> bool:
    """Is there a stderr write on every path from the function's entry here?

    Two rules, and the second is the one with teeth:

    1. In the block the return sits in, any earlier stderr write counts — it
       runs immediately before the return, in the same branch.
    2. In an OUTER block, only an *unconditional* statement before the branch
       counts. A write inside a sibling ``if`` may not have run; counting it
       would let a `--vault is required` check at the top of a verb vouch for
       every silent ``return 2`` below it, which is precisely the shape this
       guard is looking for.
    """
    for depth, (block, index) in enumerate(_path_to(func, target)):
        for stmt in block[:index]:
            if depth > 0 and isinstance(stmt, _BRANCHING):
                continue
            if _writes_to_stderr(stmt):
                return True
    return False


def _verbs() -> list[tuple[str, ast.FunctionDef]]:
    out: list[tuple[str, ast.FunctionDef]] = []
    for path in sorted(CLI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and (
                node.name.startswith("_cmd_") or node.name.startswith("cmd_")
            ):
                out.append((path.name, node))
    return out


def test_the_scan_finds_the_verbs_it_claims_to_check() -> None:
    """A guard that reports zero having looked at nothing is the #283 failure
    mode. There are ~20 argparse verbs; if this drops to a handful, the
    discovery is broken, not the codebase."""
    verbs = _verbs()
    assert len(verbs) >= 15, f"only found {len(verbs)} CLI verb functions"
    names = {name for _, func in verbs for name in [func.name]}
    assert "_cmd_pipeline" in names
    assert "cmd_digest" in names


def test_every_nonzero_return_reports_a_reason_on_stderr() -> None:
    offenders: list[str] = []
    for module, func in _verbs():
        if (module, func.name) in ALLOWLIST:
            continue
        for ret in _nonzero_returns(func):
            if not _reason_reaches(func, ret):
                offenders.append(
                    f"{module}:{ret.lineno}  {func.name} returns "
                    f"{ast.unparse(ret.value)} having written nothing to stderr"
                )
    assert offenders == [], (
        "spec 070 FR6: a non-zero exit must say what it rejected. Write the "
        "reason to stderr before returning, or — if the code is deliberately "
        "not an error (a declined confirmation, say) — add the function to "
        "ALLOWLIST in this file with a one-line reason:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


def test_the_allowlist_has_no_stale_entries() -> None:
    """An allowlist that outlives its reason is a hole nobody knows is open."""
    live = {(module, func.name) for module, func in _verbs()}
    stale = sorted(entry for entry in ALLOWLIST if entry not in live)
    assert stale == [], "ALLOWLIST names functions that no longer exist: " + ", ".join(
        f"{m}::{f}" for m, f in stale
    )


def test_the_detector_does_not_let_a_top_of_function_check_vouch_for_the_rest(
    tmp_path: Path,
) -> None:
    """The first draft of this guard passed on its first run, which for a
    codebase with ~20 verbs is a result worth distrusting. It was counting any
    stderr write anywhere earlier in the function — so the near-universal
    ``if args.vault is None: print(..., file=sys.stderr); return 2`` at the top
    vouched for every silent return below it. These two shapes are the whole
    difference, and the guard has to tell them apart."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import sys\n"
        "def _cmd_top_only(args):\n"
        "    if args.vault is None:\n"
        "        print('error: --vault is required', file=sys.stderr)\n"
        "        return 2\n"
        "    if args.other:\n"
        "        return 2\n"
        "    return 0\n"
        "def _cmd_unconditional(args):\n"
        "    print('error: something', file=sys.stderr)\n"
        "    if args.other:\n"
        "        return 2\n"
        "    return 0\n",
        encoding="utf-8",
    )
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    top_only = _nonzero_returns(funcs["_cmd_top_only"])
    assert [_reason_reaches(funcs["_cmd_top_only"], r) for r in top_only] == [
        True,
        False,
    ], "a guarded check at the top must not vouch for a later silent return"

    unconditional = _nonzero_returns(funcs["_cmd_unconditional"])
    assert [_reason_reaches(funcs["_cmd_unconditional"], r) for r in unconditional] == [
        True
    ], "an unconditional write before the branch IS on the path"
