"""`pause show | clear` — read or abandon a pause marker (issue #237).

``budget-marker.contract.md`` §5 has listed "operator aborts cycle (explicit
cleanup command)" as a clear condition since spec 033 was planned, and nothing
implemented it. Abandoning a paused cycle meant deleting
``_pipeline/BUDGET_PAUSED`` by hand, and no verb would first tell you what the
marker said — which stage stopped, what the blocked dispatch was going to
cost, how much the cycle had already spent. The information was on disk the
whole time.

Two verbs, two different jobs, and the difference is deliberate:

``show`` is a **read-only inspector**, and it is at its most useful precisely
when a marker is malformed — so it never fails on one. It reports what it
found, including "this file exists and this build cannot read it", and exits
0. Failing there would take the diagnostic away at the moment it is needed.

``clear`` **destroys operator state**, so it never happens by accident: on a
TTY it renders the marker and asks; headless it requires ``--yes``. It is also
the one place a marker this build cannot parse may be deleted —
``budget_resume`` deliberately refuses to (resuming over an unreadable pause
would drop whichever cap stopped the run), which left an unreadable marker
with no sanctioned way out at all.

Clearing an approval pause records NO decision. ``approval-decisions.json`` is
the record of verdicts an operator reached (approval-marker.contract.md §6.1);
walking away from a gate is not a verdict, and writing ``approved: false`` for
it would put a decision in the cycle report that nobody made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from research_framework.cli._tty import is_interactive_tty
from research_framework.pipeline.budget_guard import (
    approval_marker_path,
    budget_marker_path,
    clear_approval_marker,
    clear_budget_marker,
    validate_approval_required_marker,
    validate_budget_paused_marker,
)

#: Rendered in this order, and the order is the resume path's precedence:
#: "budget marker checked before APPROVAL_REQUIRED when both exist"
#: (budget-marker.contract.md §4). What `show` prints first is what the
#: operator has to resolve first.
_MARKERS: tuple[tuple[str, str], ...] = (
    ("budget", "BUDGET_PAUSED"),
    ("approval", "APPROVAL_REQUIRED"),
)

#: The fields each marker kind puts in front of a human, in the order a
#: decision needs them. Deliberately the SAME fields the resume path re-checks
#: (budget-marker.contract.md §4.3, approval-marker.contract.md §5.1 step 1),
#: because a `show` that renders a different set is a second reader of the
#: same state and will drift from the first.
_BUDGET_FIELDS: tuple[tuple[str, str], ...] = (
    ("pause_reason", "reason"),
    ("paused_stage", "stage"),
    ("paused_at", "written at"),
    ("cumulative_spend_usd", "spent so far"),
    ("cycle_budget_usd", "cycle cap"),
    ("dispatch_estimate_usd", "blocked dispatch est."),
    ("codex_tokens_cumulative", "metered tokens"),
    ("codex_token_budget", "metered-token cap"),
    ("wallclock_elapsed_seconds", "elapsed (s)"),
    ("wallclock_cap_seconds", "wall-clock cap (s)"),
    ("blocked_dispatch_preview", "blocked prompt"),
)
_APPROVAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("stage_name", "stage"),
    ("tier", "tier"),
    ("agent", "agent"),
    ("paused_at", "written at"),
    ("estimated_cost_usd", "estimated cost"),
    ("cumulative_spend_usd", "spent so far"),
    ("prompt_preview", "prompt"),
)
_USD_FIELDS = frozenset(
    {
        "cumulative_spend_usd",
        "cycle_budget_usd",
        "dispatch_estimate_usd",
        "estimated_cost_usd",
    }
)


def _marker_path(kind: str, vault: Path) -> Path:
    return (
        budget_marker_path(vault) if kind == "budget" else approval_marker_path(vault)
    )


def _validate(kind: str, doc: dict[str, Any]) -> None:
    if kind == "budget":
        validate_budget_paused_marker(doc)
    else:
        validate_approval_required_marker(doc)


def _read_marker(kind: str, vault: Path) -> dict[str, Any] | None:
    """Return a render-ready record, or ``None`` when no such marker stands.

    ``readable`` is part of the record rather than an exception, because "the
    pause exists and this build cannot read it" is the single most useful
    thing this verb can tell an operator — it is exactly the state
    ``budget_resume`` refuses to act on.
    """
    path = _marker_path(kind, vault)
    if not path.is_file():
        return None
    record: dict[str, Any] = {"path": str(path), "readable": True, "error": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("marker is not a JSON object")
        _validate(kind, doc)
        record.update(doc)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        record["readable"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def _format_value(field: str, value: Any) -> str:
    if field in _USD_FIELDS and isinstance(value, (int, float)):
        return f"${float(value):.4f}"
    return str(value)


def _render_marker(label: str, record: dict[str, Any], fields) -> list[str]:
    lines = [f"{label}  ({record['path']})"]
    if not record["readable"]:
        lines.append(f"  unreadable: {record['error']}")
        lines.append(
            "  `pause clear` is the sanctioned way out; a resume deliberately "
            "refuses to act on a marker it cannot read."
        )
        return lines
    cycle = record.get("cycle_number")
    if cycle is not None:
        lines.append(f"  cycle {cycle}")
    for field, label_text in fields:
        value = record.get(field)
        if value is None:
            continue
        lines.append(f"  {label_text:<22} {_format_value(field, value)}")
    return lines


def _render_text(records: dict[str, dict[str, Any] | None]) -> str:
    blocks: list[str] = []
    for kind, filename in _MARKERS:
        record = records[kind]
        if record is None:
            continue
        fields = _BUDGET_FIELDS if kind == "budget" else _APPROVAL_FIELDS
        blocks.append("\n".join(_render_marker(filename, record, fields)))
    if not blocks:
        return "No pause markers in this vault — nothing is waiting on you."
    blocks.append(
        "Resume with `research-framework generate --resume` (add "
        "`--force-budget` / `--approve <stage>` as the pause requires), or "
        "abandon it with `research-framework pause clear`."
    )
    return "\n\n".join(blocks)


def _selected(kinds: str) -> tuple[str, ...]:
    return tuple(k for k, _ in _MARKERS) if kinds == "all" else (kinds,)


def _cmd_pause(args: argparse.Namespace) -> int:
    vault: Path = args.vault.expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2
    if args.pause_cmd == "show":
        return _show(vault, json_out=bool(getattr(args, "json", False)))
    return _clear(
        vault,
        kinds=_selected(getattr(args, "marker", "all")),
        acknowledged=bool(getattr(args, "yes", False)),
    )


def _show(vault: Path, *, json_out: bool) -> int:
    records = {kind: _read_marker(kind, vault) for kind, _ in _MARKERS}
    if json_out:
        print(
            json.dumps(
                {
                    "paused": any(r is not None for r in records.values()),
                    "budget": records["budget"],
                    "approval": records["approval"],
                },
                indent=2,
            )
        )
    else:
        print(_render_text(records))
    return 0


def _clear(vault: Path, *, kinds: tuple[str, ...], acknowledged: bool) -> int:
    records = {kind: _read_marker(kind, vault) for kind in kinds}
    standing = {kind: rec for kind, rec in records.items() if rec is not None}
    if not standing:
        print("No pause markers to clear.")
        return 0

    names = dict(_MARKERS)
    summary = "\n\n".join(
        "\n".join(
            _render_marker(
                names[kind],
                rec,
                _BUDGET_FIELDS if kind == "budget" else _APPROVAL_FIELDS,
            )
        )
        for kind, rec in standing.items()
    )

    if not acknowledged:
        if not is_interactive_tty():
            print(
                "error: `pause clear` deletes the operator's record of why a "
                "run stopped. Pass --yes to acknowledge it headless.",
                file=sys.stderr,
            )
            return 1
        print(summary)
        answer = input("Abandon the pause above and delete the marker(s)? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Left the pause standing.", file=sys.stderr)
            return 1

    for kind in standing:
        if kind == "budget":
            clear_budget_marker(vault)
        else:
            # No ApprovalDecision row: abandoning a gate is not a verdict
            # (approval-marker.contract.md §6.1).
            clear_approval_marker(vault)
    cleared = ", ".join(names[kind] for kind in standing)
    print(f"Cleared: {cleared}. The paused cycle will be re-run from its start.")
    return 0
