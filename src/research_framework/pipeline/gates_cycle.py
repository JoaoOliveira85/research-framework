"""Per-cycle gates CG-001..CG-007 (feature 017, spec Story 9a)."""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.abstraction import (
    resolve_forbidden_filename_prefixes,
)
from research_framework.pipeline.coverage import compute_yield_target
from research_framework.pipeline.gates import GateResult
from research_framework.spec.schema import SpecConfig


def CG001_min_cycle_yield(
    vault_dir: Path,
    report: dict,
    *,
    cycle_number: int,
    max_cycles: int,
) -> GateResult:
    """Minimum per-cycle note yield (spec 051 FR1 configurable model).

    The threshold is ``base × cadence_factor × coverage_factor`` clamped to
    ``[min_floor, max_ceiling]`` (see ``coverage.compute_yield_target``).
    PASS at/above target; a single WARN band for ``floor ≤ n < target``
    (under-target but non-trivial); FAIL only below ``min_floor`` (i.e. a
    zero/near-zero cycle). The multiplier breakdown is included so the gate is
    auditable from the cycle report alone.
    """
    yt = compute_yield_target(vault_dir, cycle_number, max_cycles)
    threshold = yt.target
    n = len(report.get("notes_created") or [])
    if threshold == 0:
        # No remaining coverage work — a complete vault has no mandatory yield.
        return GateResult(
            gate_id="CG-001",
            status="PASS",
            metric_name="notes_created_this_cycle",
            metric_value=n,
            threshold=0,
            message=(
                f"{n} note(s); all coverage targets met — no minimum yield "
                "required this cycle"
            ),
        )
    breakdown = (
        f"target {threshold} = base {yt.base} × {yt.cadence_bucket} "
        f"{yt.cadence_factor:g} × {yt.coverage_bucket} {yt.coverage_factor:g} "
        f"[floor {yt.floor}, ceiling {yt.ceiling}]"
    )
    if n >= threshold:
        return GateResult(
            gate_id="CG-001",
            status="PASS",
            metric_name="notes_created_this_cycle",
            metric_value=n,
            threshold=threshold,
            message=f"{n} note(s) meet minimum yield ({breakdown})",
        )
    if n < yt.floor:
        return GateResult(
            gate_id="CG-001",
            status="FAIL",
            metric_name="notes_created_this_cycle",
            metric_value=n,
            threshold=threshold,
            message=f"{n} note(s) below floor {yt.floor} ({breakdown})",
            correction_hint=(
                f"Write at least {yt.floor} note(s) this cycle; aim for "
                f"{threshold} ({breakdown})."
            ),
        )
    return GateResult(
        gate_id="CG-001",
        status="WARN",
        metric_name="notes_created_this_cycle",
        metric_value=n,
        threshold=threshold,
        message=f"{n} note(s) below target yield ({breakdown})",
        correction_hint=(
            f"Increase output toward {threshold} note(s) before closing the "
            f"cycle ({breakdown})."
        ),
    )


def CG002_category_diversity(
    cycle_notes: list[dict], *, unfilled_categories: int
) -> GateResult:
    threshold = min(5, unfilled_categories)
    if not cycle_notes:
        return GateResult(
            gate_id="CG-002",
            status="PASS",
            metric_name="distinct_coverage_categories",
            metric_value=0,
            threshold=threshold,
            message="no cycle notes — category spread gate skipped",
        )
    cats: list[str] = []
    for row in cycle_notes:
        c = row.get("category")
        cats.append(str(c).strip() if c is not None else "")
    distinct = len(set(cats))
    if distinct == 1:
        return GateResult(
            gate_id="CG-002",
            status="FAIL",
            metric_name="distinct_coverage_categories",
            metric_value=distinct,
            threshold=threshold,
            message="all cycle notes share one coverage_category",
            correction_hint=(
                f"Single-category cycle; need spread across ≥ {threshold} categories "
                f"(min(5, unfilled_categories={unfilled_categories}))."
            ),
        )
    if distinct < 3:
        return GateResult(
            gate_id="CG-002",
            status="WARN",
            metric_name="distinct_coverage_categories",
            metric_value=distinct,
            threshold=threshold,
            message=f"only {distinct} distinct categor(ies); prefer ≥ 3",
            correction_hint="Broaden coverage_category mix toward high-priority gaps.",
        )
    if distinct >= threshold:
        return GateResult(
            gate_id="CG-002",
            status="PASS",
            metric_name="distinct_coverage_categories",
            metric_value=distinct,
            threshold=threshold,
            message=f"{distinct} distinct categories meets threshold {threshold}",
        )
    return GateResult(
        gate_id="CG-002",
        status="WARN",
        metric_name="distinct_coverage_categories",
        metric_value=distinct,
        threshold=threshold,
        message=f"{distinct} distinct categories below threshold {threshold}",
        correction_hint=(
            f"Need notes in at least {threshold} distinct coverage_category values."
        ),
    )


def _cg003_thresholds() -> tuple[float, float]:
    """Cycle vault-filename abstraction bands (spec Story 9a CG-003: 30 / 60)."""
    return 30.0, 60.0


def _cg003_violates(filename: str, prefixes: list[str]) -> bool:
    name = filename.lower()
    return any(name.startswith(p.lower()) for p in prefixes)


def CG003_filename_abstraction_check(
    spec: SpecConfig, data_vault_files: list[str], vault_dir: Path
) -> GateResult:
    """CG-003: ratio of vault filenames matching the abstraction prefixes.

    Shares SG-003's prefix source (``pipeline.abstraction``) so the cycle gate
    and the scout gate can never be active on different lists — or, as before,
    both inactive because a spec key nothing writes was left empty.
    """
    prefixes = resolve_forbidden_filename_prefixes(spec, vault_dir)
    if prefixes is None:
        return GateResult(
            gate_id="CG-003",
            status="NA",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=0.0,
            threshold=None,
            message=(
                "abstraction gate switched off in settings.yaml "
                "(pipeline.gates.abstraction_enabled: false)"
            ),
        )
    warn_pct, fail_pct = _cg003_thresholds()
    warn_frac = warn_pct / 100.0
    files = [str(f) for f in data_vault_files if str(f).strip()]
    if not files:
        return GateResult(
            gate_id="CG-003",
            status="PASS",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=0.0,
            threshold=warn_frac,
            message="no vault filenames to check — ratio 0",
        )
    violations = sum(1 for f in files if _cg003_violates(Path(f).name, prefixes))
    ratio = violations / len(files)
    pct = ratio * 100.0
    if pct > fail_pct:
        hit_prefixes = sorted(
            {
                p
                for f in files
                for p in prefixes
                if Path(f).name.lower().startswith(p.lower())
            }
        )
        hint = (
            "Vault filenames match forbidden prefixes ("
            + ", ".join(hit_prefixes)
            + "). Use generalizable note titles."
        )
        return GateResult(
            gate_id="CG-003",
            status="FAIL",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=ratio,
            threshold=warn_frac,
            message=(
                f"{violations}/{len(files)} files ({pct:.1f}%) match forbidden prefixes "
                f"— above fail threshold {fail_pct}%"
            ),
            correction_hint=hint,
        )
    if pct > warn_pct:
        return GateResult(
            gate_id="CG-003",
            status="WARN",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=ratio,
            threshold=warn_frac,
            message=(
                f"{violations}/{len(files)} files ({pct:.1f}%) match forbidden prefixes "
                f"— above warn threshold {warn_pct}%"
            ),
            correction_hint="Reduce internal-artifact filenames; align with scout abstraction gate.",
        )
    return GateResult(
        gate_id="CG-003",
        status="PASS",
        metric_name="forbidden_prefix_violation_ratio",
        metric_value=ratio,
        threshold=warn_frac,
        message=(
            f"{violations}/{len(files)} files ({pct:.1f}%) match forbidden prefixes "
            f"— within {warn_pct}%"
        ),
    )


def CG004_avg_word_count(
    before: dict,
    after: dict,
    expected_per_cycle: int,
    categories: list[str],
) -> GateResult:
    if expected_per_cycle < 1:
        raise ValueError("expected_per_cycle must be >= 1")
    if not categories:
        return GateResult(
            gate_id="CG-004",
            status="PASS",
            metric_name="coverage_velocity_ratio",
            metric_value=1.0,
            threshold=0.5,
            message="no categories in scope — velocity gate skipped",
        )
    ratios: list[float] = []
    zero_unfilled = False
    for cat in categories:
        b = before.get(cat) or {}
        a = after.get(cat) or {}
        b_met = int(b.get("met") or 0)
        a_met = int(a.get("met") or 0)
        delta = a_met - b_met
        ratios.append(delta / float(expected_per_cycle))
        if b_met == 0 and delta == 0:
            zero_unfilled = True
    min_ratio = min(ratios)
    if zero_unfilled and min_ratio == 0.0:
        return GateResult(
            gate_id="CG-004",
            status="FAIL",
            metric_name="coverage_velocity_ratio",
            metric_value=min_ratio,
            threshold=0.5,
            message="zero met_count progress on at least one category still at zero",
            correction_hint=(
                "Advance coverage in categories that were completely empty at "
                "cycle start."
            ),
        )
    if min_ratio >= 0.5:
        return GateResult(
            gate_id="CG-004",
            status="PASS",
            metric_name="coverage_velocity_ratio",
            metric_value=min_ratio,
            threshold=0.5,
            message=f"per-category progress min {min_ratio:.2f} × expected meets 0.5 bar",
        )
    if min_ratio > 0.0:
        return GateResult(
            gate_id="CG-004",
            status="WARN",
            metric_name="coverage_velocity_ratio",
            metric_value=min_ratio,
            threshold=0.5,
            message=f"progress ratio {min_ratio:.2f} below 0.5 of expected per-category",
            correction_hint="Increase notes mapped to under-filled categories this cycle.",
        )
    return GateResult(
        gate_id="CG-004",
        status="FAIL",
        metric_name="coverage_velocity_ratio",
        metric_value=0.0,
        threshold=0.5,
        message="no positive coverage delta versus expected velocity",
        correction_hint="Coverage velocity is zero while targets remain; write more notes.",
    )


def CG005_cumulative_coverage_trajectory(
    coverage_snapshot: dict,
    *,
    max_cycles: int,
    current_cycle: int,
) -> GateResult:
    if current_cycle < 1 or max_cycles < 1:
        raise ValueError("current_cycle and max_cycles must be >= 1")
    if not coverage_snapshot:
        return GateResult(
            gate_id="CG-005",
            status="WARN",
            metric_name="projected_final_fill_pct",
            metric_value=0.0,
            threshold=0.7,
            message="empty coverage snapshot — cannot project trajectory",
            correction_hint="Coverage targets not loaded; verify coverage-targets.json.",
        )
    fills: list[float] = []
    for _k, v in coverage_snapshot.items():
        if isinstance(v, dict):
            fills.append(float(v.get("fill_pct") or 0.0))
    fill_avg = sum(fills) / len(fills) if fills else 0.0
    rate = fill_avg / float(current_cycle)
    projected = fill_avg + (max_cycles - current_cycle) * rate
    projected = min(1.0, projected)
    if projected >= 0.7:
        return GateResult(
            gate_id="CG-005",
            status="PASS",
            metric_name="projected_final_fill_pct",
            metric_value=projected,
            threshold=0.7,
            message=f"projected fill {projected:.2f} at max_cycles meets 70% bar",
        )
    return GateResult(
        gate_id="CG-005",
        status="WARN",
        metric_name="projected_final_fill_pct",
        metric_value=projected,
        threshold=0.7,
        message=f"projected fill {projected:.2f} below 70% at current pace",
        correction_hint="Raise per-cycle yield or extend budget to hit coverage goals.",
    )


def CG006_word_count_compliance(
    word_counts: list[int], *, min_floor: int
) -> GateResult:
    if min_floor < 1:
        raise ValueError("min_floor must be >= 1")
    short_line = min_floor * 0.6
    total = len(word_counts)
    if total == 0:
        return GateResult(
            gate_id="CG-006",
            status="PASS",
            metric_name="notes_below_word_floor_ratio",
            metric_value=0.0,
            threshold=0.1,
            message="no notes scored for word count",
        )
    violations = sum(1 for w in word_counts if w < short_line)
    ratio = violations / total
    if ratio > 0.3:
        return GateResult(
            gate_id="CG-006",
            status="FAIL",
            metric_name="notes_below_word_floor_ratio",
            metric_value=ratio,
            threshold=0.1,
            message=f"{violations}/{total} notes materially below word floor ({ratio:.0%})",
            correction_hint=(
                f"Expand notes to meet min_word_count≈{min_floor}; too many thin drafts."
            ),
        )
    if ratio >= 0.1:
        return GateResult(
            gate_id="CG-006",
            status="WARN",
            metric_name="notes_below_word_floor_ratio",
            metric_value=ratio,
            threshold=0.1,
            message=f"{violations}/{total} notes below relaxed floor (60% of {min_floor})",
            correction_hint="Thicken short notes to clear the word-count compliance band.",
        )
    return GateResult(
        gate_id="CG-006",
        status="PASS",
        metric_name="notes_below_word_floor_ratio",
        metric_value=ratio,
        threshold=0.1,
        message=f"{violations}/{total} notes below relaxed compliance line",
    )


def CG007_orphan_link_pct(dead: int, total: int) -> GateResult:
    if total < 0 or dead < 0:
        raise ValueError("dead and total must be non-negative")
    if total == 0:
        return GateResult(
            gate_id="CG-007",
            status="PASS",
            metric_name="orphan_wikilink_ratio",
            metric_value=0.0,
            threshold=0.2,
            message="no wikilinks audited — ratio defined as 0",
        )
    ratio = dead / total
    if ratio > 0.6:
        return GateResult(
            gate_id="CG-007",
            status="FAIL",
            metric_name="orphan_wikilink_ratio",
            metric_value=ratio,
            threshold=0.2,
            message=f"orphan link ratio {ratio:.2f} extremely high ({dead}/{total})",
            correction_hint="Repair or remove dead wikilinks; regenerate cross-references.",
        )
    if ratio > 0.2:
        return GateResult(
            gate_id="CG-007",
            status="WARN",
            metric_name="orphan_wikilink_ratio",
            metric_value=ratio,
            threshold=0.2,
            message=f"orphan link ratio {ratio:.2f} above 20% ({dead}/{total})",
            correction_hint="Reduce dead wikilinks in new notes before the next cycle.",
        )
    return GateResult(
        gate_id="CG-007",
        status="PASS",
        metric_name="orphan_wikilink_ratio",
        metric_value=ratio,
        threshold=0.2,
        message=f"orphan link ratio {ratio:.2f} within limit",
    )
