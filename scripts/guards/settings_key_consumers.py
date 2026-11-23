#!/usr/bin/env python3
"""Guard: every key of the typed ``pipeline:`` settings schema has a reader.

Spec 087 SC-005, plan decision 14. ``settings.yaml`` has shipped keys that the
loader accepts, validates and documents while nothing reads them (spec 076 D1:
``research_modes``, the ``cg_00x`` thresholds). A typed key is a promise that
setting it changes something; this guard fails when the promise has no taker.

**What it checks.** Every key under ``pipeline:`` in the loader's schema
(``research_framework.pipeline.settings._SCHEMA``: the typed fields and the keys
other modules read from the raw file) must be *referenced* by at least one
module outside ``pipeline/settings.py`` -- under ``src/research_framework/`` or
``scripts/`` -- as an identifier (``settings.cycle_split``) or a string literal
(``pipeline.get("max_batches_per_cycle")``). Docstrings and comments do not
count, for the reason ``parser_flag_consumers`` gives: prose is how an unread
option looks read.

**What it does not check.** A module that reads the key and then ignores the
value passes. Like its sibling this is a floor, not dataflow analysis.

Fail-closed: :class:`ConsumptionReport` carries the keys and files seen, and
the test asserts floors on both before it asserts the invariant.

Usage:
    python scripts/guards/settings_key_consumers.py [--list]
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

try:  # imported as ``scripts.guards.<module>`` (tests) or run as a script
    from ._checkout_package import require_checkout_package
except ImportError:
    from _checkout_package import require_checkout_package

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src" / "research_framework"
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"
_SETTINGS_MODULE = _SRC_ROOT / "pipeline" / "settings.py"
_THIS_FILE = Path(__file__).resolve()

#: Pipeline keys that are read by name but never as a Python identifier or a
#: string key, keyed by key with the reason. An entry here is a debt, and ``stale_allowlist`` goes red once it has a reader.
ALLOWLIST: dict[str, str] = {
    "cycle_split": "read by the plan generator in spec 087 T007; T006 only declares it",
}


@dataclass
class ConsumptionReport:
    keys: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    stale_allowlist: list[str] = field(default_factory=list)


def pipeline_keys() -> list[str]:
    """The keys of the ``pipeline:`` block in the loader's schema."""
    if str(_REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
    require_checkout_package(_REPO_ROOT)
    from research_framework.pipeline import settings

    return sorted(settings._SCHEMA["pipeline"])


def consumer_files() -> list[Path]:
    """Every module that could read a pipeline key, except the loader itself."""
    files = [
        p
        for root in (_SRC_ROOT, _SCRIPTS_ROOT)
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    return sorted(
        p for p in files if p.resolve() not in (_SETTINGS_MODULE.resolve(), _THIS_FILE)
    )


def referenced_names(path: Path) -> set[str]:
    """Identifiers and string literals a module uses (docstrings excluded).

    Raises ``SyntaxError`` for a module that will not parse: one this guard
    cannot read must be loud, not silently un-guarding every key.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
            ):
                docstrings.add(id(body[0].value))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                names.add(node.value)
    return names


def audit(
    keys: Iterable[str] | None = None, files: Iterable[Path] | None = None
) -> ConsumptionReport:
    report = ConsumptionReport(
        keys=list(pipeline_keys() if keys is None else keys),
        files=list(consumer_files() if files is None else files),
    )
    seen: set[str] = set()
    for path in report.files:
        seen |= referenced_names(path)
    for key in report.keys:
        if key not in seen and key not in ALLOWLIST:
            report.unread.append(key)
    report.stale_allowlist = [k for k in ALLOWLIST if k in seen or k not in report.keys]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the keys audited")
    args = parser.parse_args(argv)
    report = audit()
    if args.list:
        for key in report.keys:
            print(key)
        return 0
    if report.unread:
        print(
            "pipeline settings key(s) declared in the schema but read by no "
            "module outside pipeline/settings.py:",
            file=sys.stderr,
        )
        for key in report.unread:
            print(f"  pipeline.{key}", file=sys.stderr)
        print(
            "Wire the key to a consumer, or remove it from the schema.",
            file=sys.stderr,
        )
        return 1
    if report.stale_allowlist:
        print(f"stale allowlist entries: {report.stale_allowlist}", file=sys.stderr)
        return 1
    print(
        f"settings-key-consumers: {len(report.keys)} pipeline keys, "
        f"{len(report.files)} consumer modules, all read."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
