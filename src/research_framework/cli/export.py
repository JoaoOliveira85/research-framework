"""`export --claims` — the vault→consumer distillation as a verb (issue #189).

The verb is deliberately thin: it resolves the vault, picks the export kind,
and hands the envelope to stdout or ``--out``. Everything a consumer could
argue with — which files are plumbing, how credibility resolves, what the
envelope looks like — lives in ``vault.claims_export`` behind
``tests/contracts/claims-export-1.0.schema.json``, so the contract is tested
where it is produced, not where it is printed.

Exit codes follow spec 077: ``0`` exported, ``2`` invalid input (no vault, no
corpus, no export kind). Reasons go to stderr (spec 070 FR6); the envelope is
the only thing ever written to stdout, so ``./vault export --claims | jq``
works.

``--claims`` is the only export this build offers, and it is still a flag
rather than the default: an ``export`` with no kind selected is a usage error
today, so that a second kind can be added later without changing what a bare
``export`` means.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from research_framework.vault.claims_export import (
    ClaimsExportError,
    export_claims,
    render_claims_json,
)


def _cmd_export(args: argparse.Namespace) -> int:
    vault: Path = args.vault.expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2
    if not args.claims:
        print(
            "error: nothing selected to export — pass --claims (the only "
            "export this build offers).",
            file=sys.stderr,
        )
        return 2
    try:
        doc = export_claims(vault, include_quarantined=bool(args.include_quarantined))
    except ClaimsExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = render_claims_json(doc)
    out: Path | None = args.out
    if out is None:
        sys.stdout.write(text)
        return 0
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(
        f"wrote {doc['counts']['claims']} claims "
        f"(schema {doc['schema_version']}) to {out}",
        file=sys.stderr,
    )
    return 0
