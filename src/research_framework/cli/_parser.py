"""Argparse topology for research-framework CLI (SC-009 order preserved)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._log_level import add_log_level_arg
from .acceptance import _cmd_acceptance
from .audit import _cmd_check_skills, _cmd_coverage, _cmd_validate
from .digest import cmd_digest
from .export import _cmd_export
from .pause import _cmd_pause
from .quality import _cmd_quality_baseline_update, _cmd_quality_fixture_init
from .refresh_sources import cmd_refresh_sources
from .regenerate_shim import cmd_regenerate_shim
from .regrade import _cmd_regrade
from .research_cycles import _cmd_cycle, _cmd_pipeline
from .research_generate import _cmd_generate
from .status import cmd_status
from .vault import (
    _cmd_inventory,
    _cmd_onboard,
    _cmd_parse_spec,
    _cmd_prune,
    _cmd_regenerate_agents,
    _cmd_reindex,
)
from .wikilinks import cmd_wikilinks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-framework", description="Knowledge vault generator."
    )
    add_log_level_arg(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate a vault from a spec file")
    g.add_argument(
        "vault_dir",
        type=Path,
        nargs="?",
        default=None,
        help=(
            "Vault root directory. With --regenerate-plan-only, required unless "
            "--output is set; spec is read from <vault_dir>/research.spec.md."
        ),
    )
    g.add_argument(
        "--spec",
        type=Path,
        default=None,
        help=(
            "Path to a spec file. Accepts either the simple research.spec.md "
            "format (recommended for new vaults) or the detailed vault-spec.md "
            "format (power users). Auto-detected. Not used with "
            "--regenerate-plan-only (always uses <vault>/research.spec.md)."
        ),
    )
    g.add_argument(
        "--output", type=Path, default=None, help="Override vault output directory"
    )
    g.add_argument("--dry-run", action="store_true", help="Phase 0/1 only")
    g.add_argument(
        "--resume", action="store_true", help="Skip Phase 0/1; enter Phase 2"
    )
    g.add_argument(
        "--cycle", type=int, default=None, help="Start at a specific cycle (--resume)"
    )
    g.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help=(
            "LIFETIME cycle ceiling: the highest cycle NUMBER this vault may "
            "run, counted from cycle 1 — not a count of additional cycles "
            "(issue #239). On a vault whose next cycle is 7, `--max-cycles 5` "
            "runs nothing; use --more-cycles for 'N more from here'. Top of "
            "the spec-061 ladder: beats settings.yaml `pipeline.max_cycles`. "
            "Honoured identically across generate / --resume / phase-3."
        ),
    )
    g.add_argument(
        "--more-cycles",
        type=int,
        default=None,
        metavar="N",
        help=(
            "N more cycles from wherever this vault stands — the per-run "
            "reading of the cycle ceiling (issue #239). Resolves to "
            "`<next cycle> + N - 1` and occupies the same top rung as "
            "--max-cycles, so passing both is a usage error."
        ),
    )
    g.add_argument(
        "--max-usd",
        type=float,
        default=None,
        help=(
            "LIFETIME dollar ceiling, compared against every cycle this vault "
            "has ever run (issue #239) — not a budget for this run. Overrides "
            "settings.yaml `pipeline.budget_usd` (spec 061); omit for the "
            "settings value; 0 disables the cap."
        ),
    )
    g.add_argument(
        "--max-usd-this-run",
        type=float,
        default=None,
        metavar="USD",
        help=(
            "Ceiling on what THIS run adds, measured from the vault's spend "
            "when the run starts (issue #239). Independent of --max-usd: "
            "whichever ceiling is reached first ends the run. 0 disables it."
        ),
    )
    g.add_argument(
        "--estimate-only",
        action="store_true",
        help=(
            "Cost preflight (issue #238): print the per-stage spend the budget "
            "guard would project for the next cycle and exit WITHOUT "
            "dispatching anything. Exit 2 when no `limits.cycle_budget_usd` is "
            "resolved — an unattended run with no ceiling is the finding."
        ),
    )
    g.add_argument(
        "--skip-gate", action="store_true", help="Skip Phase 1 pytest gate (testing)"
    )
    g.add_argument(
        "--prepopulate",
        type=Path,
        default=None,
        help=(
            "Directory of files to copy verbatim into the generated vault's "
            "_pipeline/ (feature 002 carry-forward — post-mortem, "
            "lessons-learned, budget-log from an archived vault)."
        ),
    )
    g.add_argument(
        "--settings",
        type=str,
        default=None,
        help=(
            "Path to the settings.yaml to bake into the generated vault. "
            "Accepts ~/$VAR expansion and relative paths. When omitted, "
            "the bundled default profile (Anthropic/Claude) is used. Pass "
            "./settings.codex.yaml to run against the OpenAI runtime, or "
            "./settings.cursor.yaml for the flat-rate Cursor runtime."
        ),
    )
    g.add_argument(
        "--regenerate-plan-only",
        action="store_true",
        help=(
            "Skip scaffolding and Phase 2/3: load <vault>/research.spec.md, infer the "
            "next cycle from _pipeline/coverage-targets.json (cycle_number+1, or 1 if "
            "missing), write _pipeline/research-plan.md and the archived copy under "
            "_pipeline/cycles/, then run the plan narrator. Ignores --resume, --dry-run, "
            "--cycle, and other generate flags that affect Phase 2."
        ),
    )
    g.add_argument(
        "--legacy-cycle-runner",
        action="store_true",
        help=(
            "DEPRECATED: pre-017 single-invocation note-writer path (removed). "
            "Emits a warning and fails — use the default pipeline instead."
        ),
    )
    g.add_argument(
        "--force-budget",
        action="store_true",
        help="Resume past BUDGET_PAUSED after operator acknowledgement (spec 033).",
    )
    g.add_argument(
        "--approve",
        type=str,
        default=None,
        metavar="STAGE",
        help="Headless approval for a gated stage (requires RF_APPROVE_<STAGE>_ACK=1).",
    )
    g.add_argument(
        "--approve-all",
        action="store_true",
        help="Approve all pending gates (requires RF_APPROVE_ALL_ACK=1 headless).",
    )
    g.add_argument(
        "--reject",
        type=str,
        default=None,
        metavar="STAGE",
        help="Reject approval for stage; retains APPROVAL_REQUIRED marker.",
    )
    g.set_defaults(func=_cmd_generate)

    c = sub.add_parser("coverage", help="Show coverage target status")
    c.add_argument("--vault", type=Path, required=True, help="Vault directory")
    c.set_defaults(func=_cmd_coverage)

    v = sub.add_parser("validate", help="Run full validation suite on a vault")
    v.add_argument("--vault", type=Path, required=True, help="Vault directory")
    v.set_defaults(func=_cmd_validate)

    r = sub.add_parser("reindex", help="Rebuild Layer 1 index files")
    r.add_argument("--vault", type=Path, required=True, help="Vault directory")
    r.set_defaults(func=_cmd_reindex)

    cs = sub.add_parser(
        "check-skills",
        help=(
            "Validate .agents/skills/*/SKILL.md and auto-restore broken ones "
            "from the bundled wheel copies."
        ),
    )
    cs.add_argument("--vault", type=Path, required=True, help="Vault directory")
    cs.set_defaults(func=_cmd_check_skills)

    cy = sub.add_parser("cycle", help="Run a single research cycle")
    cy.add_argument("--vault", type=Path, required=True, help="Vault directory")
    cy.add_argument("--cycle", type=int, required=True, help="Cycle number")
    cy.add_argument(
        "--budget-cap",
        type=float,
        default=None,
        metavar="USD",
        help=(
            "The `--max-usd` rung of the spec-061 ladder for this verb: a "
            "LIFETIME dollar ceiling across every cycle the vault has run "
            "(issue #239). Omitted, it resolves from settings.yaml "
            "`pipeline.budget_usd`; 0 disables the cap. There is no hardcoded "
            "default — that was issue #233."
        ),
    )
    cy.add_argument(
        "--estimate-only",
        action="store_true",
        help=(
            "Cost preflight (issue #238): print the projected per-stage spend "
            "for this cycle and exit without dispatching anything."
        ),
    )
    cy.add_argument(
        "--target-topics",
        nargs="+",
        default=None,
        help="Focus topics for this cycle (passed to scout prompt renderer)",
    )
    cy.set_defaults(func=_cmd_cycle)

    inv_p = sub.add_parser(
        "inventory",
        help="Produce a read-only structured snapshot of a vault's contents",
    )
    inv_p.add_argument("vault_path", type=Path, help="Path to the vault root")
    inv_p.add_argument(
        "--format",
        choices=["json", "text"],
        default=None,
        help="Output format (default: text if TTY, json otherwise)",
    )
    inv_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write output to this file instead of stdout",
    )
    inv_p.set_defaults(func=_cmd_inventory)

    ob = sub.add_parser(
        "onboard",
        help=(
            "Adopt an existing vault under the research-framework framework "
            "(git init, corpus rename, draft spec, parse-spec)."
        ),
    )
    ob.add_argument("vault_path", type=Path, help="Path to the vault root")
    ob.add_argument(
        "--draft-only",
        action="store_true",
        help="Stop after step 3 (spec draft) even if everything else is ready",
    )
    ob.add_argument(
        "--no-git",
        action="store_true",
        help="Skip all git operations (init / commit / mv)",
    )
    ob.set_defaults(func=_cmd_onboard)

    ra = sub.add_parser(
        "regenerate-agents",
        help="Overwrite .claude/commands/<agent>.md from framework templates",
    )
    ra.add_argument("vault_path", type=Path, help="Path to the vault root")
    ra.add_argument(
        "--agent",
        dest="agent",
        action="append",
        metavar="NAME",
        default=None,
        help=(
            "Agent name to regenerate (repeatable). "
            "When omitted, all 8 agents are regenerated."
        ),
    )
    ra.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt and write immediately",
    )
    ra.set_defaults(func=_cmd_regenerate_agents)

    pr = sub.add_parser(
        "prune",
        help=(
            "Remove vault-local scripts superseded by framework modules "
            "(with pre/post snapshot boundary for rollback)."
        ),
    )
    pr.add_argument("vault_path", type=Path, help="Path to the vault root")
    pr.add_argument(
        "--keep",
        action="append",
        metavar="PATH",
        default=None,
        dest="keep",
        help=(
            "Vault-relative path to exclude from deletion (repeatable). "
            "Example: --keep scripts/collect_rss.py"
        ),
    )
    pr.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )
    pr.add_argument(
        "--force",
        action="store_true",
        help="Proceed even when the vault working tree is dirty",
    )
    pr.set_defaults(func=_cmd_prune)

    ps = sub.add_parser(
        "parse-spec",
        help=(
            "Parse a research-framework spec file and (re)write the vault's "
            "_pipeline/spec-parse.json. Use this to recover a vault whose "
            "spec-parse.json was deleted or corrupted."
        ),
    )
    ps.add_argument("vault_path", type=Path, help="Path to the vault root")
    ps.add_argument(
        "spec_path",
        type=Path,
        nargs="?",
        help=(
            "Path to the spec file. Defaults to <vault>/<vault-name>-spec.md, "
            "then <vault>/research.spec.md."
        ),
    )
    ps.set_defaults(func=_cmd_parse_spec)

    # pipeline subcommand
    pl = sub.add_parser(
        "pipeline",
        help="Run the full research pipeline (collect→extract→scout→triage→research→verify→report)",
    )
    pl.add_argument("vault", type=Path, help="Vault root directory")
    pl.add_argument(
        "pipeline_cmd",
        choices=[
            "full",
            "collect",
            "extract",
            "scout",
            "resume",
            "finish",
            "status",
            "prune-runs",
        ],
        help="Pipeline subcommand to run",
    )
    pl.add_argument(
        "--budget-cap",
        type=float,
        default=None,
        metavar="USD",
        # Kept in the parser ONLY so passing it produces a named refusal
        # instead of argparse's "unrecognized arguments" (issue #232). No
        # `pipeline` phase writes a cost sidecar yet (#220/#221), so there is
        # nothing to tally a cap against.
        help=(
            "NOT IMPLEMENTED for pipeline runs — passing it is an error. Cap a "
            "run through `limits.cycle_budget_usd` in the vault's settings.yaml "
            "(or `cycle --budget-cap` for a single research cycle)."
        ),
    )
    pl.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-phase progress output",
    )
    # Spec 080 FR-020: run directories are never pruned automatically. Cap-N
    # AND age, the same shape #307 chose for research branches, so an operator
    # learns one retention policy rather than two.
    pl.add_argument(
        "--keep",
        type=int,
        default=5,
        metavar="N",
        help="prune-runs: keep the newest N run directories (default 5).",
    )
    pl.add_argument(
        "--older-than",
        type=int,
        default=90,
        metavar="DAYS",
        # dest matches ``run_receipt.prunable_runs``'s parameter, so the
        # flag-consumer guard can see the value reach the module that honours
        # it rather than stopping at the CLI boundary (#271).
        dest="older_than_days",
        help=(
            "prune-runs: keep anything younger than DAYS regardless of N "
            "(default 90). A run is removed only when it is outside BOTH "
            "bounds."
        ),
    )
    pl.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="prune-runs: list what would be removed and delete nothing.",
    )
    pl.add_argument(
        "--json",
        action="store_true",
        help=(
            "Machine-readable output for `status` (issue #245): explicit, "
            "rather than inferred from whether stdout is a TTY. Ignored by "
            "the other pipeline subcommands."
        ),
    )
    # Issue #241: the pipeline verbs are the ones built to run unattended, and
    # `_log_level` FR-005's non-TTY WARNING default silenced their entire
    # narrative — phase summaries, the triage prompt, the verify verdict. They
    # declare INFO as their own default; `--log-level` still overrides it.
    pl.set_defaults(func=_cmd_pipeline, verb_default_log_level="info")

    qbu = sub.add_parser(
        "quality-baseline-update",
        help=(
            "Bless a new quality baseline for one harness fixture "
            "(spec 022; human-only, never auto-updated by the harness)."
        ),
        description=(
            "Run the quality harness for a single fixture, show the diff "
            "against the committed baseline, and optionally overwrite the "
            "baseline after confirmation.\n\n"
            "Examples:\n"
            "  research-framework quality-baseline-update tech-lite "
            '--reason "Improved template compliance after spec 025"\n'
            "  research-framework quality-baseline-update tech-lite --dry-run\n"
            "See specs/022-e2e-quality-harness/contracts/quality-cli.contract.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    qbu.add_argument(
        "fixture",
        choices=["tech-lite", "source-poor", "source-rich"],
        help="Registered quality fixture name.",
    )
    qbu.add_argument(
        "--reason",
        default="",
        help="Rationale stored as last_updated_reason (required unless --dry-run).",
    )
    qbu.add_argument(
        "--actor",
        default="",
        help="Name stored as last_updated_by (default: $GIT_AUTHOR_NAME then $USER).",
    )
    qbu.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the diff without writing the baseline file.",
    )
    qbu.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation (CI only; rejected unless $CI is set).",
    )
    qbu.set_defaults(func=_cmd_quality_baseline_update)

    qfi = sub.add_parser(
        "quality-fixture-init",
        help="Reserved v2 helper for adding new quality fixtures (stub in v1).",
    )
    qfi.set_defaults(func=_cmd_quality_fixture_init)

    rs = sub.add_parser(
        "refresh-sources", help="Run legacy scripts/collect_*.py collectors"
    )
    rs.add_argument("--vault", type=Path, required=True, help="Vault directory")
    rs.add_argument("--json", action="store_true", help="Machine-readable stdout")
    rs.add_argument("--dry-run", action="store_true", help="List collectors only")
    rs.add_argument(
        "--only", action="append", default=None, help="Restrict to script basename"
    )
    rs.add_argument(
        "-v", "--verbose", action="store_true", help="Stream collector output"
    )
    rs.set_defaults(func=cmd_refresh_sources)

    rg = sub.add_parser("regenerate-shim", help="Re-render the vault bash shim")
    rg.add_argument("--vault", type=Path, required=True, help="Vault directory")
    rg.add_argument("--json", action="store_true", help="Machine-readable stdout")
    rg.add_argument("--dry-run", action="store_true", help="Assess without writing")
    rg.add_argument(
        "--force", action="store_true", help="Overwrite customized/unverified shim"
    )
    rg.set_defaults(func=cmd_regenerate_shim)

    st = sub.add_parser("status", help="Live vault cycle status (read-only)")
    st.add_argument("--vault", type=Path, required=True, help="Vault directory")
    st.add_argument("--json", action="store_true", help="Machine-readable stdout")
    st.set_defaults(func=cmd_status)

    dg = sub.add_parser("digest", help="Cross-cycle markdown digest (read-only)")
    dg.add_argument("--vault", type=Path, required=True, help="Vault directory")
    period = dg.add_mutually_exclusive_group()
    period.add_argument("--since", type=str, default=None, help="ISO8601 start date")
    period.add_argument(
        "--last-week", action="store_true", help="Digest the last 7 days"
    )
    period.add_argument(
        "--last-month", action="store_true", help="Digest the last 30 days"
    )
    period.add_argument(
        "--last-quarter", action="store_true", help="Digest the last 90 days"
    )
    dg.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output path (default: _pipeline/digests/digest-<start>--<end>.md)",
    )
    dg.set_defaults(func=cmd_digest)

    ac = sub.add_parser(
        "acceptance",
        help="Run the framework-generic acceptance gates (read-only; spec 063)",
    )
    ac.add_argument("--vault", type=Path, required=True, help="Vault directory")
    ac.add_argument("--json", action="store_true", help="Machine-readable stdout")
    ac.add_argument(
        "--strict",
        action="store_true",
        help="Treat WARN gates as blocking (non-zero exit)",
    )
    ac.set_defaults(func=_cmd_acceptance)

    wl = sub.add_parser(
        "wikilinks",
        help=(
            "Deterministic acronym-wikilink repair sweep (spec 067; "
            "dry-run unless --fix)"
        ),
    )
    wl.add_argument("--vault", type=Path, required=True, help="Vault directory")
    wl.add_argument(
        "--fix",
        action="store_true",
        help="Apply repairs (default: report only / dry-run)",
    )
    wl.add_argument("--json", action="store_true", help="Emit SweepActionRecord[] JSON")
    wl.set_defaults(func=cmd_wikilinks)

    rg = sub.add_parser(
        "re-grade",
        help=(
            "Re-grade quarantined notes against the current credibility model "
            "and reinstate the now-clean ones (spec 066)"
        ),
    )
    rg.add_argument("--vault", type=Path, required=True, help="Vault directory")
    rg.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + print outcomes; touch nothing, no commit",
    )
    rg.add_argument(
        "--note",
        action="append",
        default=[],
        help="Re-grade only the named quarantined note(s); repeatable",
    )
    rg.add_argument("--json", action="store_true", help="Machine-readable summary")
    rg.set_defaults(func=_cmd_regrade)

    # Appended AFTER the pre-B5 registry (SC-009 pins that prefix order), so a
    # new verb never reshuffles the existing surface.
    pz = sub.add_parser(
        "pause",
        help=(
            "Inspect or abandon a pause marker without resuming "
            "(budget-marker.contract.md §5; issue #237)"
        ),
    )
    pz.add_argument(
        "pause_cmd",
        choices=["show", "clear"],
        help=(
            "show: render the standing marker(s) read-only — reason, stage, "
            "tier, estimated $, cumulative $, written-at. "
            "clear: delete them under an explicit acknowledgement."
        ),
    )
    pz.add_argument("--vault", type=Path, required=True, help="Vault directory")
    pz.add_argument(
        "--marker",
        choices=["budget", "approval", "all"],
        default="all",
        help="Which pause to act on (default: all)",
    )
    pz.add_argument(
        "--yes",
        action="store_true",
        help="Acknowledge a `clear` without the interactive prompt (required headless)",
    )
    pz.add_argument("--json", action="store_true", help="Machine-readable `show`")
    pz.set_defaults(func=_cmd_pause)

    ex = sub.add_parser(
        "export",
        help=(
            "Export the vault as a versioned, consumer-facing envelope "
            "(claims-export 1.0; ADR-0013; issue #189)"
        ),
    )
    ex.add_argument("--vault", type=Path, required=True, help="Vault directory")
    ex.add_argument(
        "--claims",
        action="store_true",
        help=(
            "One claim record per qualifying note — plumbing skipped by the "
            "framework's own rules, citation credibility resolved as the "
            "verifier resolves it. Schema: tests/contracts/claims-export-1.0.schema.json"
        ),
    )
    ex.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the JSON here instead of stdout (parent directories are created)",
    )
    ex.add_argument(
        "--include-quarantined",
        action="store_true",
        help=(
            "Also export notes under _pipeline/quarantine/, flagged "
            "`quarantined: true` (excluded by default)"
        ),
    )
    ex.set_defaults(func=_cmd_export)

    return parser
