"""Cycle quality report assembly (feature 017, E-005)."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from research_framework import __version__
from research_framework.pipeline.atomic_write import write_json
from research_framework.pipeline.coverage import (
    YieldTarget,
    compute_yield_target,
    load_targets,
    save_targets,
)
from research_framework.pipeline.gates import GateResult, run_gate
from research_framework.pipeline.gates_cycle import (
    CG001_min_cycle_yield,
    CG002_category_diversity,
    CG003_filename_abstraction_check,
    CG004_avg_word_count,
    CG005_cumulative_coverage_trajectory,
    CG006_word_count_compliance,
    CG007_orphan_link_pct,
)
from research_framework.pipeline.settings import effective_max_cycles
from research_framework.pipeline.step_gate_log import read_step_gates
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)


def _load_spec_config(vault_dir: Path) -> SpecConfig:
    parse_path = vault_dir / "_pipeline" / "spec-parse.json"
    if parse_path.is_file():
        try:
            return SpecConfig.from_dict(
                json.loads(parse_path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    spec_md = vault_dir / "research.spec.md"
    if spec_md.is_file():
        from research_framework.spec.simple import load as load_spec

        return load_spec(spec_md, location=vault_dir)
    return SpecConfig(
        name="unknown",
        location=vault_dir,
        owner="",
        scope=ScopeConfig(domain="", organization=""),
        note_types=[],
        data_sources=[],
        search_dimensions=[],
        coverage_targets=CoverageTargets(categories=[]),
        budget=BudgetConfig(),
    )


def _load_targets_flexible(vault_dir: Path, spec: SpecConfig) -> CoverageTargets:
    try:
        return load_targets(vault_dir)
    except (FileNotFoundError, OSError, RuntimeError):
        cats = [replace(c, met_count=0) for c in spec.coverage_targets.categories]
        return CoverageTargets(categories=cats)


def _read_previous_snapshot(vault_dir: Path, cycle_number: int) -> dict[str, dict]:
    if cycle_number <= 1:
        return {}
    prev = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number - 1:03d}-quality-report.json"
    )
    if not prev.is_file():
        return {}
    try:
        data = json.loads(prev.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    snap = data.get("coverage_snapshot")
    return snap if isinstance(snap, dict) else {}


def _retry_sidecar(vault_dir: Path, cycle_number: int) -> tuple[int, bool, str]:
    p = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number:03d}-retry-state.json"
    )
    if not p.is_file():
        return 0, False, ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0, False, ""
    rc = int(data.get("retry_count") or 0)
    aborted = bool(data.get("aborted") or False)
    reason = str(data.get("abort_reason") or "")
    return rc, aborted, reason


def _degraded_sources(vault_dir: Path) -> list[str]:
    path = vault_dir / "_pipeline" / "source-incidents.md"
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = line.strip()
        if "degraded" in t.lower() and ":" in t:
            out.append(t)
        elif t.startswith("- ") and "source" in t.lower():
            out.append(t[2:].strip())
    return out


def _iter_batch_files(vault_dir: Path, cycle_number: int) -> list[Path]:
    cdir = vault_dir / "_pipeline" / "cycles"
    if not cdir.is_dir():
        return []
    prefix = f"cycle-{cycle_number:03d}-batch-"
    paths = sorted(p for p in cdir.glob(f"{prefix}*.json") if p.is_file())
    return paths


def _gate_from_json(d: dict[str, Any]) -> GateResult:
    return GateResult(
        gate_id=str(d["gate_id"]),
        status=d["status"],  # type: ignore[arg-type]
        metric_name=str(d.get("metric_name") or ""),
        metric_value=d.get("metric_value", 0),
        threshold=d.get("threshold"),
        message=str(d.get("message") or ""),
        correction_hint=str(d.get("correction_hint") or ""),
    )


def _synthetic_sg(batch_n: int, gate_suffix: str) -> GateResult:
    gid = f"SG-{gate_suffix}"
    return GateResult(
        gate_id=gid,
        status="NA",
        metric_name="batch_gate_not_recorded",
        metric_value=0,
        threshold=None,
        message=f"no {gid} result recorded for batch {batch_n}",
    )


def _word_count_body(vault_dir: Path, filename: str) -> int:
    corpus = corpus_dir(vault_dir)
    if not corpus.is_dir():
        return 0
    basename = Path(filename).name
    matches = list(corpus.rglob(basename))
    if not matches:
        return 0
    try:
        _fm, text = parse_frontmatter(matches[0])
    except (OSError, FrontmatterParseError):
        text = matches[0].read_text(encoding="utf-8", errors="replace")
    return len((text or "").split())


def _min_note_word_floor(spec: SpecConfig) -> int:
    floors = [int(nt.min_word_count) for nt in spec.note_types if nt.min_word_count]
    return min(floors) if floors else 200


def _build_coverage_snapshot(
    targets: CoverageTargets, prev_snap: dict[str, dict]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in targets.categories:
        t = max(0, int(c.target_count))
        m = max(0, int(c.met_count))
        fill = float(m) / float(t) if t else 0.0
        prev_m = 0
        prev_cat = prev_snap.get(c.name)
        if isinstance(prev_cat, dict):
            prev_m = int(prev_cat.get("met") or 0)
        out[c.name] = {
            "target": t,
            "met": m,
            "fill_pct": min(1.0, max(0.0, fill)),
            "delta_this_cycle": m - prev_m,
        }
    return out


def _notes_rejected_on_disk(vault_dir: Path, note_paths: list[str]) -> set[str]:
    """Return the subset of ``note_paths`` whose note is stamped rejected.

    Spec 070 F3. ``notes_rejected`` was derived purely from the BATCH's
    ``accepted`` flag, so a batch that passed overall reported ``0 rejected``
    even when the per-note verifier had stamped notes inside it
    ``verifier_status: rejected`` — notes the orchestrator then swept into
    ``_pipeline/quarantine/``. The live vault that surfaced this recorded
    ``notes_written: 4, notes_accepted: 4, notes_rejected: 0`` for three
    consecutive cycles while 9 notes were being destroyed.

    Reads the notes themselves, which is the only account that cannot disagree
    with what is on disk. Quarantine is checked as well so the count stays right
    if a sweep has already run.
    """
    from research_framework.vault.frontmatter import parse_frontmatter

    rejected: set[str] = set()
    quarantine = vault_dir / "_pipeline" / "quarantine"
    for rel in note_paths:
        candidate = vault_dir / rel
        if not candidate.is_file():
            candidate = quarantine / Path(rel).name
        if not candidate.is_file():
            continue
        try:
            fm, _body = parse_frontmatter(candidate)
        except Exception:  # pragma: no cover - defensive; never fail a report
            continue
        if fm and str(fm.get("verifier_status", "")).strip().lower() == "rejected":
            rejected.add(rel)
    return rejected


def _merge_sg_gates(
    vault_dir: Path, cycle_number: int
) -> tuple[
    dict[str, GateResult],
    list[str],
    int,
    int,
    int,
    str,
    str,
    list[str],
    list[dict[str, str]],
]:
    batch_paths = _iter_batch_files(vault_dir, cycle_number)
    gates: dict[str, GateResult] = {}
    batch_rejected: set[str] = set()
    all_written: list[str] = []
    cycle_notes: list[dict[str, str]] = []
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    finished = started

    sg_singleton: dict[str, GateResult | None] = {
        "SG-001": None,
        "SG-002": None,
        "SG-003": None,
    }

    if not batch_paths:
        for suf in ("004", "005"):
            gates[f"SG-{suf}#1"] = _synthetic_sg(1, suf)

    for bp in batch_paths:
        try:
            doc = json.loads(bp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        b_num = int(doc.get("batch_number") or 0)
        topics = doc.get("topics") or []
        if not isinstance(topics, list):
            topics = []
        nw = doc.get("notes_written") or []
        if not isinstance(nw, list):
            nw = []
        notes_list = [str(x) for x in nw]
        if not bool(doc.get("accepted", False)):
            batch_rejected.update(notes_list)
        all_written.extend(notes_list)
        for i, name in enumerate(notes_list):
            row = topics[i] if i < len(topics) and isinstance(topics[i], dict) else {}
            cat = str(row.get("category") or "")
            cycle_notes.append({"file": name, "category": cat})
        sa = str(doc.get("started_at") or "")
        fb = str(doc.get("finished_at") or "")
        if sa:
            started = sa
        if fb:
            finished = fb
        raw_sgs = doc.get("sg_gate_results") or []
        by_base: dict[str, GateResult] = {}
        if isinstance(raw_sgs, list):
            for item in raw_sgs:
                if isinstance(item, dict) and item.get("gate_id"):
                    try:
                        gr = _gate_from_json(item)
                        by_base[gr.gate_id] = gr
                    except (KeyError, ValueError, TypeError):
                        continue
        for suf in ("004", "005"):
            gid = f"SG-{suf}"
            gr = by_base.get(gid)
            if gr is None:
                gr = _synthetic_sg(b_num, suf)
            gates[f"{gid}#{b_num}"] = gr
        for sgid in ("SG-001", "SG-002", "SG-003"):
            if sgid in by_base and sg_singleton[sgid] is None:
                sg_singleton[sgid] = by_base[sgid]

    # Issue #269: batch reports only ever carry SG-004/SG-005, so SG-001..003
    # fell through to NA on EVERY cycle — and on a cycle a step gate aborted,
    # no batch exists at all, so the gate that stopped the cycle was the one
    # reported as "not recorded". The scout now writes its verdicts as it
    # evaluates them; read that record before giving up on the gate.
    recorded = {
        gate.gate_id: gate
        for gate in read_step_gates(vault_dir / "_pipeline" / "cycles", cycle_number)
    }
    for sgid, gr in sg_singleton.items():
        resolved = gr or recorded.get(sgid)
        gates[sgid] = resolved or GateResult(
            gate_id=sgid,
            status="NA",
            metric_name="step_gate_not_recorded",
            metric_value=0,
            threshold=None,
            message="scout did not evaluate this gate in this cycle",
        )

    # Spec 070 F3: a note is rejected if its BATCH was rejected OR the per-note
    # verifier stamped it so. Counting only the former reported "0 rejected"
    # while notes were being quarantined.
    rejected_paths = batch_rejected | _notes_rejected_on_disk(vault_dir, all_written)
    notes_rejected = len(rejected_paths)
    notes_accepted = max(0, len(all_written) - notes_rejected)

    batch_names = [p.name for p in batch_paths]
    return (
        gates,
        batch_names,
        notes_accepted,
        notes_rejected,
        len(all_written),
        started,
        finished,
        all_written,
        cycle_notes,
    )


@dataclass
class CycleQualityReport:
    cycle_number: int
    framework_version: str
    generated_at: str
    cycle_started_at: str
    cycle_finished_at: str
    gates: dict[str, GateResult]
    coverage_snapshot: dict[str, dict[str, Any]]
    notes_written: int
    notes_accepted: int
    notes_rejected: int
    batches: list[str]
    queryability_score: int
    queryability_trajectory: Literal["improving", "stable", "regressing"]
    degraded_sources: list[str]
    retry_count: int
    aborted: bool
    abort_reason: str
    schema_version: str = "1"
    cg001_yield: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d_gates: dict[str, Any] = {}
        for k, g in self.gates.items():
            d_gates[k] = g.to_dict()
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "cycle_number": self.cycle_number,
            "framework_version": self.framework_version,
            "generated_at": self.generated_at,
            "cycle_started_at": self.cycle_started_at,
            "cycle_finished_at": self.cycle_finished_at,
            "gates": d_gates,
            "coverage_snapshot": self.coverage_snapshot,
            "notes_written": self.notes_written,
            "notes_accepted": self.notes_accepted,
            "notes_rejected": self.notes_rejected,
            "batches": list(self.batches),
            "queryability_score": self.queryability_score,
            "queryability_trajectory": self.queryability_trajectory,
            "degraded_sources": list(self.degraded_sources),
            "retry_count": self.retry_count,
            "aborted": self.aborted,
        }
        payload["abort_reason"] = self.abort_reason
        if self.cg001_yield is not None:
            payload["cg001_yield"] = self.cg001_yield
        return payload


def _append_yield_calibration(
    vault_dir: Path,
    cycle_number: int,
    yt: YieldTarget,
    actual: int,
    exit_status: str,
) -> None:
    """Append this cycle's CG-001 yield record to ``_pipeline/yield-calibration.json``.

    The sidecar is the empirical record the FR1 defaults are re-tuned against in
    0.7.2 (spec 051). Idempotent per cycle: a re-run of ``write_report`` for the
    same cycle replaces that cycle's entry rather than duplicating it. Schema:
    ``specs/051-post-revival-hardening/contracts/yield-calibration.schema.json``.
    """
    path = vault_dir / "_pipeline" / "yield-calibration.json"
    existing: list[dict[str, Any]] = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [e for e in loaded if isinstance(e, dict)]
        except (json.JSONDecodeError, OSError):
            existing = []
    existing = [e for e in existing if e.get("cycle") != cycle_number]
    existing.append(
        {
            "schema_version": "1.0",
            "cycle": cycle_number,
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base": yt.base,
            "cadence_bucket": yt.cadence_bucket,
            "cadence_factor": yt.cadence_factor,
            "coverage_bucket": yt.coverage_bucket,
            "coverage_factor": yt.coverage_factor,
            "target": yt.target,
            "actual": actual,
            "exit_status": exit_status,
        }
    )
    existing.sort(key=lambda e: e.get("cycle", 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, existing)


def write_report(vault_dir: Path, cycle_number: int) -> Path:
    """Materialise the end-of-cycle quality report for ``cycle_number``.

    Reads the cycle's per-batch SG-gate envelopes from
    ``<vault>/_pipeline/cycles/cycle-NNN-batch-*.json`` plus the cumulative
    coverage targets at ``<vault>/_pipeline/coverage-targets.json``, then
    writes a single normalised JSON report to
    ``<vault>/_pipeline/cycles/cycle-NNN-quality-report.json`` describing:

    * SG-gate outcomes (accept / reject counts and gate identifiers),
    * coverage snapshot before/after the cycle (delta per category),
    * notes actually written,
    * remaining-yield projection over the configured ``max_cycles`` budget,
    * any cycle-level abort metadata (applied later by
      :func:`research_framework.pipeline._cycle_helpers._apply_exit_metadata`).

    Idempotent for a given ``(vault_dir, cycle_number)`` pair: re-running
    overwrites the report file. Bootstraps a default
    ``coverage-targets.json`` if one is missing.

    Returns:
        The :class:`pathlib.Path` of the written quality report. Callers
        typically pass this through ``_apply_exit_metadata`` to attach the
        cycle's final ``exit_code`` and ``abort_reason``.

    Side effects:
        * Writes (or creates) ``_pipeline/coverage-targets.json`` on first run.
        * Writes the quality report file.
        * Does NOT raise on missing batch envelopes — produces a report with
          zeros so the cycle-runner's exit path remains deterministic.

    See ``specs/017-vault-quality-fix/`` for the schema.
    """
    spec = _load_spec_config(vault_dir)
    targets = _load_targets_flexible(vault_dir, spec)
    ct_path = vault_dir / "_pipeline" / "coverage-targets.json"
    if not ct_path.is_file():
        ct_path.parent.mkdir(parents=True, exist_ok=True)
        save_targets(vault_dir, targets)
    prev_snap = _read_previous_snapshot(vault_dir, cycle_number)
    snap = _build_coverage_snapshot(targets, prev_snap)
    # Spec 061: the cycle horizon for the yield projection comes from the vault
    # settings (canonical pipeline.max_cycles), not the (now-removed) spec field.
    max_cycles = max(1, effective_max_cycles(vault_dir))

    (
        sg_gates,
        batch_names,
        n_acc,
        n_rej,
        n_written,
        started,
        finished,
        all_written,
        cycle_notes,
    ) = _merge_sg_gates(vault_dir, cycle_number)

    if n_written != n_acc + n_rej:
        n_written = n_acc + n_rej

    unfilled = sum(1 for c in targets.categories if c.met_count < c.target_count)
    report_for_cg1 = {"notes_created": list(all_written)}

    files_for_abstraction = [Path(f).name for f in all_written]

    before: dict[str, dict[str, int]] = {}
    after: dict[str, dict[str, int]] = {}
    cat_names = [c.name for c in targets.categories]
    for name in cat_names:
        pm = 0
        prev_row = prev_snap.get(name)
        if isinstance(prev_row, dict):
            pm = int(prev_row.get("met") or 0)
        before[name] = {"met": pm}
    for c in targets.categories:
        after[c.name] = {"met": int(c.met_count)}
    # CG-004 scores the categories that still have a target to reach (spec 017
    # FR-023: "scores 0 on unfilled categories"). Scoring every category made
    # the zero delta of a finished one the cycle's minimum, so the gate FAILed
    # every cycle once any category had filled — and FAILed a complete vault
    # for "zero velocity while targets remain". A category leaves scope only
    # while it is met at both ends of the cycle; one that dropped back under
    # its target stays in.
    velocity_cats = [
        c.name
        for c in targets.categories
        if min(before[c.name]["met"], after[c.name]["met"]) < int(c.target_count)
    ]
    yt = compute_yield_target(vault_dir, cycle_number, max_cycles)
    exp_vel = max(1, yt.target)
    wcs = [_word_count_body(vault_dir, fn) for fn in all_written]
    floor = _min_note_word_floor(spec)

    cg_gates: dict[str, GateResult] = {}
    for fn, args, kw in (
        (
            CG001_min_cycle_yield,
            (vault_dir, report_for_cg1),
            {"cycle_number": cycle_number, "max_cycles": max_cycles},
        ),
        (CG002_category_diversity, (cycle_notes,), {"unfilled_categories": unfilled}),
        (
            CG003_filename_abstraction_check,
            (spec, files_for_abstraction, vault_dir),
            {},
        ),
        (
            CG004_avg_word_count,
            (before, after, exp_vel, velocity_cats),
            {},
        ),
        (
            CG005_cumulative_coverage_trajectory,
            (snap,),
            {"max_cycles": max_cycles, "current_cycle": cycle_number},
        ),
        (CG006_word_count_compliance, (wcs,), {"min_floor": floor}),
        (CG007_orphan_link_pct, (0, 0), {}),
    ):
        gr = run_gate(fn, *args, **kw)
        cg_gates[gr.gate_id] = gr

    # FR1 (spec 051): surface the CG-001 yield breakdown in the report and
    # append it to the re-tuning sidecar. `actual`/`exit_status` come from the
    # CG-001 gate result so the diagnostic matches the gate verdict exactly.
    _cg1 = cg_gates.get("CG-001")
    cg1_actual = int(_cg1.metric_value) if _cg1 is not None else 0
    cg1_status = _cg1.status if _cg1 is not None else "FAIL"
    cg001_yield = {
        "target": yt.target,
        "base": yt.base,
        "cadence_bucket": yt.cadence_bucket,
        "cadence_factor": yt.cadence_factor,
        "coverage_bucket": yt.coverage_bucket,
        "coverage_factor": yt.coverage_factor,
        "actual": cg1_actual,
        "exit_status": cg1_status,
    }
    _append_yield_calibration(vault_dir, cycle_number, yt, cg1_actual, cg1_status)

    all_gates = {**sg_gates, **cg_gates}
    retry_count, aborted, abort_reason = _retry_sidecar(vault_dir, cycle_number)
    if aborted and retry_count != 2:
        retry_count = 2
    if aborted and not str(abort_reason).strip():
        abort_reason = "cycle aborted after exhausting retries"
    degraded = _degraded_sources(vault_dir)
    # Spec 069 FR3/FR5: advisory stagnant-source WARNs, authority-weighted,
    # appended to the existing degraded_sources surface (never blocks the cycle).
    try:
        from research_framework.pipeline.stagnant_sources import stagnant_warnings

        degraded = degraded + stagnant_warnings(vault_dir, cycle_number)
    except Exception:  # pragma: no cover - advisory signal, never fatal
        pass
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        from research_framework.pipeline import probes

        q_score, q_traj = probes.run_cycle_probes(
            vault_dir=vault_dir, spec=spec, cycle_number=cycle_number
        )
    except Exception:
        q_score, q_traj = 0, "stable"

    report = CycleQualityReport(
        cycle_number=cycle_number,
        framework_version=__version__,
        generated_at=now,
        cycle_started_at=started,
        cycle_finished_at=finished,
        gates=all_gates,
        coverage_snapshot=snap,
        notes_written=n_written,
        notes_accepted=n_acc,
        notes_rejected=n_rej,
        batches=batch_names,
        queryability_score=q_score,
        queryability_trajectory=q_traj,
        degraded_sources=degraded,
        retry_count=retry_count,
        aborted=aborted,
        abort_reason=abort_reason,
        cg001_yield=cg001_yield,
    )

    out = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number:03d}-quality-report.json"
    )
    write_json(out, report.to_dict())
    return out
