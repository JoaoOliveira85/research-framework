"""Correction directives (feature 017, E-006): gate FAIL → prompt injection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_framework.pipeline.atomic_write import write_json
from research_framework.pipeline.gates import GateResult


@dataclass
class CorrectionDirective:
    cycle_number: int
    batch_number: int | None
    failing_gate_ids: list[str]
    diagnosis: str
    required_actions: list[str]
    forbidden_actions: list[str]
    expires_after_cycle: int
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.failing_gate_ids:
            raise ValueError("CorrectionDirective.failing_gate_ids must be non-empty")
        if not self.required_actions:
            raise ValueError("CorrectionDirective.required_actions must be non-empty")
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_prompt_block(self) -> str:
        lines = [
            "# Correction directive",
            "",
            f"**Cycle**: {self.cycle_number}",
            f"**Batch**: {self.batch_number if self.batch_number is not None else 'cycle-wide'}",
            "",
            "## Diagnosis",
            "",
            self.diagnosis,
            "",
            "## Failing gates",
            "",
        ]
        for gid in self.failing_gate_ids:
            lines.append(f"- `{gid}`")
        lines.extend(
            [
                "",
                "## Required actions",
                "",
            ]
        )
        for act in self.required_actions:
            lines.append(f"- {act}")
        if self.forbidden_actions:
            lines.extend(["", "## Forbidden actions", ""])
            for act in self.forbidden_actions:
                lines.append(f"- {act}")
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "cycle_number": self.cycle_number,
            "batch_number": self.batch_number,
            "failing_gate_ids": list(self.failing_gate_ids),
            "diagnosis": self.diagnosis,
            "required_actions": list(self.required_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "expires_after_cycle": self.expires_after_cycle,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CorrectionDirective:
        return cls(
            cycle_number=int(d["cycle_number"]),
            batch_number=d.get("batch_number"),
            failing_gate_ids=list(d["failing_gate_ids"]),
            diagnosis=str(d["diagnosis"]),
            required_actions=list(d["required_actions"]),
            forbidden_actions=list(d.get("forbidden_actions") or []),
            expires_after_cycle=int(d["expires_after_cycle"]),
            generated_at=str(d.get("generated_at") or ""),
        )

    def save(self, vault_dir: Path) -> Path:
        corr = vault_dir / "_pipeline" / "corrections"
        if self.batch_number is not None:
            name = f"cycle-{self.cycle_number:03d}-batch-{self.batch_number:03d}.json"
        else:
            name = f"cycle-{self.cycle_number:03d}.json"
        path = corr / name
        write_json(path, self.to_dict())
        return path


def build_directive(
    vault_dir: Path,
    *,
    failing_gates: list[GateResult],
    cycle: int,
    batch: int | None,
) -> Path:
    ids = [g.gate_id for g in failing_gates]
    hints = [g.correction_hint for g in failing_gates if g.correction_hint]
    msgs = [g.message for g in failing_gates]
    diagnosis = (
        "Previous step failed gate(s): "
        + ", ".join(ids)
        + ". "
        + (" ".join(msgs) if msgs else "")
    ).strip()
    required_actions: list[str] = []
    for g in failing_gates:
        if g.correction_hint.strip():
            required_actions.append(f"[{g.gate_id}] {g.correction_hint.strip()}")
        elif g.status == "FAIL":
            required_actions.append(f"[{g.gate_id}] {g.message.strip()}")
    if not required_actions:
        required_actions.append(
            "Remediate the failing gate(s) before continuing the pipeline."
        )
    forbidden: list[str] = []
    for h in hints:
        lower = h.lower()
        if "do not" in lower or "don't" in lower:
            forbidden.append(h.strip())
    directive = CorrectionDirective(
        cycle_number=cycle,
        batch_number=batch,
        failing_gate_ids=ids,
        diagnosis=diagnosis or "Gate failure requires correction.",
        required_actions=required_actions,
        forbidden_actions=forbidden,
        expires_after_cycle=cycle + 1,
    )
    return directive.save(vault_dir)


def gc_expired(vault_dir: Path, current_cycle: int) -> int:
    corr = vault_dir / "_pipeline" / "corrections"
    if not corr.is_dir():
        return 0
    removed = 0
    for p in corr.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            exp = int(raw.get("expires_after_cycle", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if exp < current_cycle:
            p.unlink(missing_ok=True)
            removed += 1
    return removed
