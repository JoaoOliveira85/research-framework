"""Spec 083 T010: the verb is wired into the parser, the shim and the 077 table."""

from __future__ import annotations

from pathlib import Path

from research_framework._assets import asset_path
from research_framework.cli import build_parser

REPO = Path(__file__).resolve().parents[2]


def test_the_verb_is_in_help_and_the_contract_table() -> None:
    parser = build_parser()
    ns = parser.parse_args(["migrate-layout", "--vault", "v", "--dry-run", "--force"])
    assert ns.dry_run and ns.force and ns.func.__name__ == "cmd_migrate_layout"

    shim = (asset_path("templates") / "vault-script.sh.j2").read_text(encoding="utf-8")
    assert "  migrate-layout)" in shim
    assert "research_framework.cli migrate-layout --vault" in shim
    assert "./vault migrate-layout" in shim  # listed in `./vault help`

    table = (REPO / "specs/077-cli-contract/spec.md").read_text(encoding="utf-8")
    assert "| `migrate-layout` |" in table
