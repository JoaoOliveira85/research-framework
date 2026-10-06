"""Per-step scout gates SG-001–SG-003 (feature 017, spec Story 9b).

Each gate is a pure function returning :class:`~research_framework.pipeline.gates.GateResult`.
SG-004 and SG-005 live in the same module under separate tasks (T042); keep one public
function per gate and no mutable module-level state so later gates can be appended
without merge conflicts.

Callers at the orchestrator boundary should wrap invocations with
:func:`~research_framework.pipeline.gates.run_gate` so unexpected exceptions become structured
FAIL results; gate bodies raise :exc:`ValueError` only for programmer errors (invalid
parameters), not for domain outcomes.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from research_framework.pipeline.abstraction import (
    gates_settings,
    resolve_forbidden_filename_prefixes,
)
from research_framework.pipeline.gates import GateResult
from research_framework.spec.schema import SpecConfig
from research_framework.vault.frontmatter import split_frontmatter


def normalise_topic_row(entry: object) -> dict | None:
    """Coerce a ``topics_found.new`` row into a dict, accepting bare strings.

    Scout outputs vary across runtimes: claude tends to emit fully structured
    rows ({"title": ..., "coverage_category": ..., "note_type": ...}) while
    codex/gpt frequently emits bare strings (["AlphaEvolve", ...]). The
    schema considers both shapes valid as long as ``title`` is recoverable.

    Returns ``None`` for rows that carry no extractable title (e.g. empty
    strings, ints, non-string-non-dict shapes). All call sites that read
    ``topics_found.new`` MUST go through this helper so the framework
    behaves identically for both shapes.
    """
    if isinstance(entry, dict):
        title = entry.get("title")
        if isinstance(title, str) and title.strip():
            return entry
        return None
    if isinstance(entry, str):
        stripped = entry.strip()
        if not stripped:
            return None
        return {"title": stripped}
    return None


def _topics_found_new_rows(scout_report: dict) -> list[dict]:
    raw = scout_report.get("topics_found")
    if not isinstance(raw, dict):
        return []
    new = raw.get("new")
    if not isinstance(new, list):
        return []
    rows: list[dict] = []
    for row in new:
        normalised = normalise_topic_row(row)
        if normalised is not None:
            rows.append(normalised)
    return rows


def SG001_topics_new_nonempty(
    scout_report: dict, _spec: SpecConfig, cycle_quota: int
) -> GateResult:
    """SG-001: scout's ``topics_found.new`` must contain ≥ ``cycle_quota`` items.

    **PASS** — ``count >= cycle_quota``.

    **WARN** — ``0 < count < cycle_quota`` (scout produced some topics but not enough
    for the planned quota).

    **FAIL** — ``count == 0`` (empty or missing ``topics_found.new``), including when
    ``new`` is absent or not a list — treated as zero topics. Carries a
    ``correction_hint`` for the orchestrator's correction directive.

    **Raises** — :exc:`ValueError` if ``cycle_quota < 1``.

    ``_spec`` is accepted for signature parity with SG-002/SG-003 and future use
    (e.g. logging vault name); it is not read today.

    Args:
        scout_report: Scout JSON dict; expects ``topics_found.new`` as a list of topic
            rows (dicts). Non-dict rows are ignored for counting.
        _spec: Parsed vault spec (unused).
        cycle_quota: Minimum number of ``topics_found.new`` rows required for PASS.
    """
    if cycle_quota < 1:
        raise ValueError(f"cycle_quota must be >= 1, got {cycle_quota}")
    rows = _topics_found_new_rows(scout_report)
    count = len(rows)
    if count == 0:
        return GateResult(
            gate_id="SG-001",
            status="FAIL",
            metric_name="topics_found_new_count",
            metric_value=0,
            threshold=cycle_quota,
            message="topics_found.new is empty — note-writer has no generalized topics",
            correction_hint=(
                "Populate topics_found.new with at least one generalizable topic title "
                f"per scout output; cycle_quota={cycle_quota}. "
                "Derive engineering-concept titles from code and external sources, not "
                "internal artifact names."
            ),
        )
    if count >= cycle_quota:
        return GateResult(
            gate_id="SG-001",
            status="PASS",
            metric_name="topics_found_new_count",
            metric_value=count,
            threshold=cycle_quota,
            message=f"topics_found.new has {count} topic(s), meeting cycle quota {cycle_quota}",
        )
    return GateResult(
        gate_id="SG-001",
        status="WARN",
        metric_name="topics_found_new_count",
        metric_value=count,
        threshold=cycle_quota,
        message=(
            f"topics_found.new has {count} topic(s), below cycle quota {cycle_quota}"
        ),
        correction_hint=(
            f"Scout returned fewer topics ({count}) than cycle_quota ({cycle_quota}). "
            "Consider broader sourcing or lowering quota if the scout is exhausted."
        ),
    )


def SG002_topic_category_diversity(
    scout_report: dict, _spec: SpecConfig, unfilled_categories: int
) -> GateResult:
    """SG-002: ``topics_found.new`` must span enough distinct ``coverage_category`` values.

    Categories are read from each topic row's ``coverage_category`` field (missing or
    empty string counts as the same bucket).

    Let ``threshold = min(5, unfilled_categories)``. **PASS** when
    ``distinct_categories >= threshold`` or when there are no topic rows (vacuous).
    **FAIL** when there is at least one topic row and
    ``distinct_categories < threshold``. The spec Story 9b failure mode "all topics share
    a single category" is covered when ``threshold > 1``.

    ``_spec`` is reserved for forward-compatible call sites; it is not read today.

    Args:
        scout_report: Scout JSON dict with ``topics_found.new`` list.
        _spec: Parsed vault spec (unused).
        unfilled_categories: Number of categories still under target; caps the diversity
            threshold at 5.
    """
    rows = _topics_found_new_rows(scout_report)
    threshold = min(5, unfilled_categories)
    if not rows:
        return GateResult(
            gate_id="SG-002",
            status="PASS",
            metric_name="distinct_coverage_categories",
            metric_value=0,
            threshold=threshold,
            message="no topics_found.new rows — diversity gate skipped",
        )
    categories: list[str] = []
    for row in rows:
        cat = row.get("coverage_category")
        categories.append(str(cat).strip() if cat is not None else "")
    distinct = len(set(categories))
    # Tolerance for the codex/gpt bare-string scout output (normalise_topic_row
    # wraps strings as {"title": ...} with no coverage_category). When EVERY
    # row is uncategorised the diversity signal is vacuous — degrade to WARN
    # so the downstream topic-classifier skill gets a chance to enrich.
    if categories and all(c == "" for c in categories):
        return GateResult(
            gate_id="SG-002",
            status="WARN",
            metric_name="distinct_coverage_categories",
            metric_value=0,
            threshold=threshold,
            message=(
                f"no topics carried a coverage_category (all {len(rows)} "
                "uncategorised) — downstream classifier will enrich; "
                "diversity gate degraded"
            ),
        )
    if distinct >= threshold:
        return GateResult(
            gate_id="SG-002",
            status="PASS",
            metric_name="distinct_coverage_categories",
            metric_value=distinct,
            threshold=threshold,
            message=(
                f"{distinct} distinct coverage_category value(s), "
                f"meeting threshold {threshold}"
            ),
        )
    return GateResult(
        gate_id="SG-002",
        status="FAIL",
        metric_name="distinct_coverage_categories",
        metric_value=distinct,
        threshold=threshold,
        message=(
            f"only {distinct} distinct coverage_category value(s); "
            f"need at least {threshold}"
        ),
        correction_hint=(
            f"topics_found.new spans {distinct} categor(ies); "
            f"require ≥ {threshold} distinct coverage_category values "
            f"(min(5, unfilled_categories={unfilled_categories})). "
            "Propose topics across multiple coverage gaps, not a single folder."
        ),
    )


def _canonical_filename_for_topic(row: dict) -> str:
    raw = row.get("proposed_filename")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    title = row.get("title")
    base = str(title).lower().replace(" ", "_") if title is not None else ""
    return f"{base}.md" if base else ".md"


def _violates_prefix(filename: str, prefixes: list[str]) -> str | None:
    for p in prefixes:
        if filename.startswith(p.lower()):
            return p
    return None


def _load_sg003_percent_thresholds(vault_dir: Path) -> tuple[float, float]:
    """Return ``(warn_pct, fail_pct)`` as 0–100 floats from vault ``settings.yaml``."""
    warn = 20.0
    fail = 60.0
    gates = gates_settings(vault_dir)
    if "sg_003_abstraction_warn_pct" in gates:
        warn = float(gates["sg_003_abstraction_warn_pct"])
    if "sg_003_abstraction_fail_pct" in gates:
        fail = float(gates["sg_003_abstraction_fail_pct"])
    return warn, fail


def SG003_topic_abstraction_check(
    scout_report: dict, spec: SpecConfig, vault_dir: Path
) -> GateResult:
    """SG-003: ratio of ``topics_found.new`` whose canonical filename matches forbidden prefixes.

    Prefixes come from ``spec.forbidden_filename_prefixes`` when the vault declares
    any, else the framework starter set — see
    :data:`~research_framework.pipeline.abstraction.DEFAULT_FORBIDDEN_FILENAME_PREFIXES`.
    **NA** only when the vault sets ``pipeline.gates.abstraction_enabled: false``.

    Filename for each topic: lowercased ``proposed_filename`` if present, else
    ``title.lower().replace(' ', '_') + '.md'``. A topic **violates** if the filename
    starts with any prefix (compared lowercased with ``str.startswith``).

    Band rules (percentages read from ``<vault_dir>/settings.yaml`` under
    ``pipeline.gates.sg_003_abstraction_warn_pct`` / ``sg_003_abstraction_fail_pct``,
    defaulting to 20 and 60):

    - **PASS** — violation ratio × 100 ≤ warn_pct.
    - **WARN** — warn_pct < ratio × 100 ≤ fail_pct.
    - **FAIL** — ratio × 100 > fail_pct; ``correction_hint`` lists each prefix that
      matched at least one violating topic, verbatim from the spec list.

    ``metric_name`` is ``forbidden_prefix_violation_ratio``; ``metric_value`` is the
    ratio in ``[0.0, 1.0]``; ``threshold`` is ``warn_pct / 100.0``.

    Args:
        scout_report: Scout JSON dict with ``topics_found.new``.
        spec: Parsed vault spec (provides ``forbidden_filename_prefixes``).
        vault_dir: Vault root (for loading ``settings.yaml`` gate thresholds).
    """
    prefixes = resolve_forbidden_filename_prefixes(spec, vault_dir)
    if prefixes is None:
        return GateResult(
            gate_id="SG-003",
            status="NA",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=0.0,
            threshold=None,
            message=(
                "abstraction gate switched off in settings.yaml "
                "(pipeline.gates.abstraction_enabled: false)"
            ),
        )
    warn_pct, fail_pct = _load_sg003_percent_thresholds(vault_dir)
    warn_frac = warn_pct / 100.0
    rows = _topics_found_new_rows(scout_report)
    if not rows:
        return GateResult(
            gate_id="SG-003",
            status="PASS",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=0.0,
            threshold=warn_frac,
            message="no topics_found.new rows — abstraction ratio 0",
        )
    violating_prefixes_hit: list[str] = []
    violations = 0
    for row in rows:
        filename = _canonical_filename_for_topic(row)
        hit = _violates_prefix(filename, prefixes)
        if hit is not None:
            violations += 1
            if hit not in violating_prefixes_hit:
                violating_prefixes_hit.append(hit)
    ratio = violations / len(rows)
    pct = ratio * 100.0
    prefix_part = ", ".join(violating_prefixes_hit)
    if pct > fail_pct:
        return GateResult(
            gate_id="SG-003",
            status="FAIL",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=ratio,
            threshold=warn_frac,
            message=(
                f"{violations}/{len(rows)} topics ({pct:.1f}%) match forbidden filename "
                f"prefixes — above fail threshold {fail_pct}%"
            ),
            correction_hint=(
                f"Topics name internal artifacts (prefixes: {prefix_part}). "
                "Replace with engineering-concept titles per scout SKILL Step 0."
            ),
        )
    if pct > warn_pct:
        return GateResult(
            gate_id="SG-003",
            status="WARN",
            metric_name="forbidden_prefix_violation_ratio",
            metric_value=ratio,
            threshold=warn_frac,
            message=(
                f"{violations}/{len(rows)} topics ({pct:.1f}%) match forbidden prefixes — "
                f"above warn threshold {warn_pct}%"
            ),
            correction_hint=(
                "Scout output exceeds the warn band for forbidden filename prefixes; "
                "generalize titles before note-writing."
            ),
        )
    return GateResult(
        gate_id="SG-003",
        status="PASS",
        metric_name="forbidden_prefix_violation_ratio",
        metric_value=ratio,
        threshold=warn_frac,
        message=(
            f"{violations}/{len(rows)} topics ({pct:.1f}%) match forbidden prefixes — "
            f"within limit {warn_pct}%"
        ),
    )


_REPO_ROOT = Path(__file__).resolve().parents[3]
"""Package file is under ``src/research_framework/pipeline/`` — three parents → repo
root **in source-tree mode**. Under a wheel install this resolves to a path
inside ``site-packages/`` that has no ``scripts/`` directory, which is why
``SG004_validate_vault_wrapper`` resolves the script via ``vault_dir/scripts``
first (every generated vault carries its own copy) and only falls back to the
source-tree path when the vault copy is missing."""


def _resolve_validate_vault_script(vault_dir: Path) -> Path | None:
    """Locate ``validate_vault.py`` in the vault, then in the dev source tree.

    Why two locations:

    - Every generated vault carries a copy under ``<vault>/scripts/`` (Step 4
      of the cycle uses this path too — see ``cycle_runner.py``).
    - In dev mode the source tree's ``scripts/`` is also a valid location and
      keeps the gate runnable when iterating on the framework itself.

    The old implementation pointed at ``_REPO_ROOT/scripts/validate_vault.py``
    unconditionally, which silently 404'd under a wheel install (the wheel does
    not vendor the script next to the package) and caused SG-004 to log the
    same false WARN on every batch.
    """
    vault_copy = vault_dir / "scripts" / "validate_vault.py"
    if vault_copy.is_file():
        return vault_copy
    source_copy = _REPO_ROOT / "scripts" / "validate_vault.py"
    if source_copy.is_file():
        return source_copy
    return None


# ``scripts/validate_vault.py`` prints each violation as two lines:
#
#     FAIL  data_vault/Widget 2.md
#           duplicate: OS-style numbered sibling of 'Widget.md'
#
# The field name on the second line is that script's ``DUPLICATE_FIELD``
# contract constant. It is the only signal in the wrapper's stdout that
# separates a constitutional Principle-VI violation from a style finding, and
# the two must not share a severity. Matching is anchored so a note whose
# *message* happens to contain the word cannot forge one.
_DUPLICATE_VIOLATION_RE = re.compile(r"^\s+duplicate:\s")


def _duplicate_violations(stdout: str) -> list[str]:
    """Principle-VI (duplicate note) violation lines in validate_vault's stdout."""
    return [
        line.strip()
        for line in stdout.splitlines()
        if _DUPLICATE_VIOLATION_RE.match(line)
    ]


def SG004_validate_vault_wrapper(vault_dir: Path) -> GateResult:
    """SG-004: run ``scripts/validate_vault.py`` on ``vault_dir``; map its result
    to PASS / WARN / FAIL.

    **PASS** — subprocess exit code 0. ``metric_name`` is ``validate_vault_exit_code``;
    ``metric_value`` is ``0``.

    **FAIL (duplicate notes)** — the script reported at least one ``duplicate``
    violation. Constitution Principle VI ("Two notes for the same concept MUST
    NOT exist") is non-negotiable and this gate is its only post-write backstop:
    mapping it to WARN meant a duplicate that slipped the pre-write
    ``proposed_filenames`` check was detected, logged, and written anyway.
    A FAIL rejects the batch and hands the note-writer a correction directive —
    the loop already built for exactly this (``steps/research.py``). It does not
    delete anything.

    **WARN** — any other non-zero exit (style, frontmatter and hygiene findings,
    or the script's own abort). Spec 017 chose WARN deliberately for these —
    "log violations for next cycle" — and spec 019 US5 kept a soft default for
    backwards compatibility. That judgement stands; what it never covered was a
    constitutional violation, which is why only the duplicate class is
    separated out. ``metric_name`` is ``validate_vault_violations``;
    ``metric_value`` is a truncated stdout summary. ``message`` includes a
    stderr snippet when stderr is non-empty.

    **FAIL (missing script)** — the script could not be located at all (broken
    install / missing scaffold). This is a setup bug, not transient noise, so it
    fails loud with a ``correction_hint`` that points at the resolver. Previously
    this case was silently swallowed as a WARN with a confusing ``[Errno 2]``
    stderr.

    **Raises** — :exc:`subprocess.TimeoutExpired` after 300s.

    Args:
        vault_dir: Vault root directory passed as the script's positional argument.
    """
    script_path = _resolve_validate_vault_script(vault_dir)
    if script_path is None:
        return GateResult(
            gate_id="SG-004",
            status="FAIL",
            metric_name="validate_vault_missing",
            metric_value="not_found",
            threshold=None,
            message=(
                "validate_vault.py not found in vault scripts/ nor in source tree; "
                "the vault scaffold is incomplete"
            ),
            correction_hint=(
                "re-run ./generate.sh (or re-install the bundle) to restore "
                "scripts/validate_vault.py inside the vault"
            ),
        )
    completed = subprocess.run(
        [sys.executable, str(script_path), str(vault_dir)],
        capture_output=True,
        timeout=300,
        cwd=script_path.parent.parent,
        check=False,
    )
    if completed.returncode == 0:
        return GateResult(
            gate_id="SG-004",
            status="PASS",
            metric_name="validate_vault_exit_code",
            metric_value=0,
            threshold=None,
            message="validate_vault.py exited 0 — no reported violations",
        )
    out = (completed.stdout or b"").decode(errors="replace")
    summary = out[:500]
    err_raw = (completed.stderr or b"").decode(errors="replace").strip()
    err_snip = err_raw[:500] if err_raw else ""
    duplicates = _duplicate_violations(out)
    if duplicates:
        listed = "; ".join(duplicates[:5])
        more = f" (+{len(duplicates) - 5} more)" if len(duplicates) > 5 else ""
        return GateResult(
            gate_id="SG-004",
            status="FAIL",
            metric_name="validate_vault_duplicate_notes",
            metric_value=len(duplicates),
            threshold=0,
            message=(
                f"constitutional Principle VI violated — {len(duplicates)} "
                f"duplicate note(s) in the vault: {listed}{more}"
            ),
            correction_hint=(
                "two notes for the same concept must not exist: merge the "
                "duplicate into the canonical note (keep the richer body and the "
                "union of its source_urls) and delete the fork, then re-check "
                "the batch's filenames against the scout's proposed_filenames"
            ),
        )
    msg = f"validate_vault.py exited {completed.returncode} — violations reported" + (
        f"; stderr: {err_snip}" if err_snip else ""
    )
    return GateResult(
        gate_id="SG-004",
        status="WARN",
        metric_name="validate_vault_violations",
        metric_value=summary,
        threshold=None,
        message=msg,
    )


_SG005_REQUIRED_KEYS = ("coverage_category", "source_urls", "summary")


def _sg005_frontmatter_dict(note_path: Path) -> dict | None:
    # Holdout from spec 025 B4 canonical parser migration.
    # Reason: SG-005 records missing/malformed frontmatter as gate failures
    # without raising; the canonical parser raises on malformed YAML.
    split = split_frontmatter(note_path.read_text(encoding="utf-8"))
    if split is None:
        return None
    try:
        fm = yaml.safe_load(split[0]) or {}
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _sg005_missing_keys(fm: dict | None) -> list[str]:
    if not fm:
        return list(_SG005_REQUIRED_KEYS)
    missing: list[str] = []
    for key in _SG005_REQUIRED_KEYS:
        if not fm.get(key):
            missing.append(key)
    return missing


def SG005_frontmatter_completeness(note_paths: list[Path]) -> GateResult:
    """SG-005: every note must have truthy ``coverage_category``, ``source_urls``, and ``summary``.

    Frontmatter is the YAML block between the first pair of ``---`` delimiters, parsed
    with :func:`yaml.safe_load`. Missing delimiter block, malformed YAML, or a
    non-mapping document are treated as missing all required keys.

    **PASS** — every path has all three keys with truthy values (non-empty string,
    non-empty ``source_urls`` list, etc.). ``metric_value`` is ``1.0``.

    **FAIL** — any note lacks a key or has an empty string / empty list for it.
    ``correction_hint`` lists each offending file and which keys are missing.
    ``metric_value`` is the ratio of fully complete notes to paths in ``[0.0, 1.0]``.

    Args:
        note_paths: Markdown note paths to inspect (batch from note-writer).
    """
    if not note_paths:
        return GateResult(
            gate_id="SG-005",
            status="PASS",
            metric_name="frontmatter_completeness_ratio",
            metric_value=1.0,
            threshold=1.0,
            message="no notes in batch — completeness vacuously satisfied",
        )
    complete = 0
    problems: list[tuple[str, list[str]]] = []
    for p in note_paths:
        fm = _sg005_frontmatter_dict(p)
        miss = _sg005_missing_keys(fm)
        if not miss:
            complete += 1
        else:
            problems.append((p.name, miss))
    ratio = complete / len(note_paths)
    if not problems:
        return GateResult(
            gate_id="SG-005",
            status="PASS",
            metric_name="frontmatter_completeness_ratio",
            metric_value=float(ratio),
            threshold=1.0,
            message=(
                f"all {len(note_paths)} note(s) have coverage_category, "
                "source_urls, and summary"
            ),
        )
    hint_parts: list[str] = []
    for name, keys in sorted(problems, key=lambda t: t[0]):
        key_list = ", ".join(keys)
        hint_parts.append(f"{name} missing: {key_list}")
    correction = "; ".join(hint_parts)
    return GateResult(
        gate_id="SG-005",
        status="FAIL",
        metric_name="frontmatter_completeness_ratio",
        metric_value=float(ratio),
        threshold=1.0,
        message=(
            f"{len(problems)}/{len(note_paths)} note(s) lack required frontmatter fields"
        ),
        correction_hint=correction,
    )
