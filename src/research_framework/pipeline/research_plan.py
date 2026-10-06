"""Deterministic research plan generator (T017, feature 017).

Produces ``_pipeline/research-plan.md`` at the start of every cycle. The
file is the single source of truth that downstream agents (scout,
note-writer, plan-narrator) read for "what to do this cycle, what to
avoid, and how to rank topics."

The plan body is deterministic: same inputs → byte-identical output. The
optional ``## Focus rationale`` header is filled in by
``pipeline/plan_narrator.py`` (R-005) and is **advisory only** — every
control-flow decision is made off the deterministic body below it.

Inputs (per ``research.md`` R-009):

- ``_pipeline/coverage-targets.json`` — current met/target per category.
- ``_pipeline/research-backlog.md`` — orphan wikilinks emitted by
  ``scripts/topic_harvest.py``; we re-rank them with the citation
  formula ``0.3 + 0.1 * citation_count`` capped at ``1.0``.
- ``_pipeline/rejects.json`` — verifier persistent-reject ledger; topics
  with ``reject_count >= 2`` enter the exclusion list so the next cycle
  does not re-propose them.
- ``data_vault/`` — already-covered filenames (Principle VI dedup
  source).
- ``spec.scope.out_of_scope`` — author-declared scope guard.

Outputs (in-memory ``ResearchPlan``; the caller writes to disk):

- ``coverage_state``: per-category fill state for the markdown table.
- ``priority_queue``: ranked topic queue for the cycle (spec-gap
  placeholders + orphans).
- ``cycle_focus``: the ≤ 3 highest-priority lowest-fill categories the
  scout MUST hit ≥ 70% of (Step 0.5 in the scout skill, R-010).
- ``cycle_quota``: ``ceil(unfilled / remaining_cycles)`` — the FR-017
  per-cycle minimum.
- ``exclusions``: deduped already-covered + persistent-rejects +
  out-of-scope, formatted as bullet lines.

Constants (kept intentionally small so the queue stays bounded; see R-009
"raises ValueError if no priority-queue topics meet the cycle quota"):

- ``_HIGH_PRIORITY_THRESHOLD = 50`` — categories at or above qualify
  for ``cycle_focus`` selection.
- ``_MAX_PLACEHOLDERS_PER_CATEGORY = 5`` — caps spec-gap topics per
  category so a single 500-target category cannot fake a quota of 500.
- ``_PERSISTENT_REJECT_THRESHOLD = 2`` — verifier rejection count at
  which a topic enters the exclusion list (matches R-009).
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import yaml

from .. import __version__ as _FRAMEWORK_VERSION
from ..spec.schema import CoverageTargets, SpecConfig, SpecValidationError
from .coverage import existing_vault_filenames, grow_targets_if_met, load_targets
from .gates_step import normalise_topic_row
from .settings import SettingsError, effective_max_cycles, load_vault_settings

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
"""Bumped on breaking layout changes per ``contracts/research-plan.schema.md``."""

_HIGH_PRIORITY_THRESHOLD = 50
"""Categories with ``priority >= 50`` qualify as "high priority" for
``cycle_focus`` selection. Below this they participate in the queue but
not the per-cycle focus directive."""

_MAX_PLACEHOLDERS_PER_CATEGORY = 5
"""Historical cap used by :func:`_placeholder_titles`. Placeholder
*generation* is disabled as of v0.2.21 — the cycle runner now merges
scout's ``topics_found.new`` into the queue post-Step-1, so synthetic
``"flows: focus topic 3"``-style stubs are no longer required to keep
the priority queue non-empty. The constant + helpers are retained so
that (a) external callers that round-trip placeholder topics through
batch reports still get detected and filtered, and (b) any future
opt-in flag can re-enable padding without re-deriving the cap. See
:data:`PLACEHOLDER_PROVENANCE` and :func:`is_placeholder_topic`."""

_PERSISTENT_REJECT_THRESHOLD = 2
"""Reject-count threshold at which a topic is dropped into
``exclusions``. Matches ``research.md`` R-009: "persistent rejects (notes
the verifier rejected ≥ 2 times)"."""

_ORPHAN_BULLET_RE = re.compile(
    r"^\s*-\s+\*\*([^*]+)\*\*\s+—\s+cited by\s+(\d+)\s+note",
    re.MULTILINE,
)
"""Match the orphan bullet emitted by ``scripts/topic_harvest.py``::

    - **Orphan Title** — cited by N note(s): `sample`

We only need ``title`` and ``citation_count``; the source samples after
the colon are informational and not propagated into the plan."""

_SECTIONS = (
    "## Focus rationale",
    "## Coverage state",
    "## Cycle focus",
    "## Priority queue",
    "## Exclusions",
)
"""Section ordering enforced by ``ResearchPlan.from_markdown``. Adding
a new section is a forward-compatible change ONLY if it is appended
after ``## Exclusions`` (per the contract's "forward compatibility"
clause); inserting one in the middle requires a ``schema_version`` bump."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CategoryFillState:
    """Snapshot of one ``CoverageCategory`` at plan-generation time.

    Pure data — no behaviour. Drives the ``## Coverage state`` markdown
    table and the ``cycle_focus`` selector.
    """

    name: str
    target_count: int
    met_count: int
    fill_pct: float
    priority: int
    unmet_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_count": self.target_count,
            "met_count": self.met_count,
            "fill_pct": self.fill_pct,
            "priority": self.priority,
            "unmet_topics": list(self.unmet_topics),
        }


@dataclass
class PrioritizedTopic:
    """A single ranked topic in the cycle's queue.

    ``priority_score`` is normalised to ``[0.0, 1.0]`` so spec-gap and
    harvest-orphan provenance can be ordered against each other on the
    same scale.
    """

    title: str
    category: str
    priority_score: float
    source_hints: list[str] = field(default_factory=list)
    provenance: str = "spec_gap"
    citation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "priority_score": self.priority_score,
            "source_hints": list(self.source_hints),
            "provenance": self.provenance,
            "citation_count": self.citation_count,
        }


@dataclass
class ResearchPlan:
    """The hybrid research plan written before each cycle (E-002)."""

    cycle_number: int
    generated_at: str
    framework_version: str
    coverage_state: list[CategoryFillState]
    priority_queue: list[PrioritizedTopic]
    cycle_focus: list[str]
    cycle_quota: int
    exclusions: list[str]
    narrative_header: str = ""

    # ----- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "generated_at": self.generated_at,
            "framework_version": self.framework_version,
            "schema_version": SCHEMA_VERSION,
            "coverage_state": [c.to_dict() for c in self.coverage_state],
            "priority_queue": [t.to_dict() for t in self.priority_queue],
            "cycle_focus": list(self.cycle_focus),
            "cycle_quota": self.cycle_quota,
            "exclusions": list(self.exclusions),
            "narrative_header": self.narrative_header,
        }

    def to_markdown(self) -> str:
        """Render the plan to its on-disk Markdown shape.

        The output conforms to ``contracts/research-plan.schema.md``
        (5 sections in fixed order, frontmatter contract). The
        ``## Focus rationale`` body is the value of ``narrative_header``
        as-is — empty string on first generation; ``plan_narrator.py``
        rewrites it later.
        """
        fm = {
            "cycle_number": int(self.cycle_number),
            "generated_at": str(self.generated_at),
            "framework_version": str(self.framework_version),
            "cycle_quota": int(self.cycle_quota),
            "schema_version": SCHEMA_VERSION,
        }
        fm_yaml = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).rstrip()

        lines: list[str] = ["---", fm_yaml, "---", ""]

        # ## Focus rationale (advisory; narrator may rewrite)
        lines.append("## Focus rationale")
        lines.append("")
        if self.narrative_header.strip():
            lines.append(self.narrative_header.strip())
            lines.append("")

        # ## Coverage state
        lines.append("## Coverage state")
        lines.append("")
        lines.append("| Category | Target | Met | Fill % | Priority | Unmet topics |")
        lines.append("|----------|--------|-----|--------|----------|--------------|")
        for c in self.coverage_state:
            topics = ", ".join(c.unmet_topics[:5]) if c.unmet_topics else "—"
            lines.append(
                f"| {c.name} | {c.target_count} | {c.met_count} | "
                f"{int(round(c.fill_pct * 100))}% | {c.priority} | {topics} |"
            )
        lines.append("")

        # ## Cycle focus
        lines.append("## Cycle focus")
        lines.append("")
        lines.append(
            "This cycle MUST produce ≥ 70% of its notes in the following categories:"
        )
        lines.append("")
        fill_by_name = {c.name: c.fill_pct for c in self.coverage_state}
        for name in self.cycle_focus:
            pct = int(round(fill_by_name.get(name, 0.0) * 100))
            lines.append(f"- {name} ({pct}% filled)")
        lines.append("")

        # ## Priority queue
        lines.append("## Priority queue")
        lines.append("")
        lines.append("Each entry: `<title> · category · score · provenance · sources`.")
        lines.append("")
        for i, t in enumerate(self.priority_queue, start=1):
            sources = ", ".join(t.source_hints) if t.source_hints else "—"
            prov = (
                f"{t.provenance}({t.citation_count})"
                if t.provenance == "harvest_orphan" and t.citation_count
                else t.provenance
            )
            lines.append(
                f"{i}. {t.title} · {t.category} · {t.priority_score:.2f} "
                f"· {prov} · {sources}"
            )
        lines.append("")

        # ## Exclusions
        lines.append("## Exclusions")
        lines.append("")
        lines.append(
            "The note-writer MUST NOT propose any topic whose canonical "
            "filename matches:"
        )
        lines.append("")
        if self.exclusions:
            for ex in self.exclusions:
                lines.append(f"- {ex}")
        else:
            lines.append("- (none)")
        lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def from_markdown(cls, text: str) -> Self:
        """Parse a written plan back into a `ResearchPlan`.

        Enforces (per ``contracts/research-plan.schema.md``):

        - YAML frontmatter is present and well-formed.
        - All five sections appear in the documented order; missing or
          re-ordered sections raise ``ValueError`` with a "malformed"
          message — downstream code MUST refuse to render prompts off a
          malformed plan.

        ``coverage_state`` and ``exclusions`` are read back from their
        sections as ``to_markdown`` writes them: the scout merge
        (``steps/scout.py``) renders the parsed plan over the file, so
        whatever is not reconstructed here is erased from the plan the
        note-writer reads. ``priority_queue`` is NOT reconstructed —
        callers that need it parse ``## Priority queue`` themselves
        (``_parse_priority_queue_from_plan_md``). ``unmet_topics`` come
        back as the (at most five) names the table shows.
        """
        if not text.lstrip().startswith("---"):
            raise ValueError("malformed plan: missing YAML frontmatter")
        body_after_first = text.lstrip()[3:]
        end_marker = body_after_first.find("\n---")
        if end_marker < 0:
            raise ValueError("malformed plan: YAML frontmatter not terminated by '---'")
        try:
            fm = yaml.safe_load(body_after_first[:end_marker]) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"malformed plan: invalid YAML — {exc}") from exc

        body = body_after_first[end_marker + 4 :]

        positions: list[int] = []
        for section in _SECTIONS:
            i = body.find(section)
            if i < 0:
                raise ValueError(
                    f"malformed plan: missing required section {section!r}"
                )
            positions.append(i)
        if positions != sorted(positions):
            raise ValueError(
                "malformed plan: required sections out of order — expected "
                + " → ".join(_SECTIONS)
            )

        section_text: dict[str, str] = {}
        for j, section in enumerate(_SECTIONS):
            start = positions[j] + len(section)
            end = positions[j + 1] if j + 1 < len(_SECTIONS) else len(body)
            section_text[section] = body[start:end]

        narrative_header = section_text["## Focus rationale"].strip()

        cycle_focus: list[str] = []
        for raw in section_text["## Cycle focus"].splitlines():
            line = raw.strip()
            if not line.startswith("- "):
                continue
            rest = line[2:].strip()
            if not rest or rest.startswith("("):
                continue
            name = rest.split(" (", 1)[0].strip()
            if name:
                cycle_focus.append(name)

        return cls(
            cycle_number=int(fm.get("cycle_number", 0) or 0),
            generated_at=str(fm.get("generated_at", "") or ""),
            framework_version=str(fm.get("framework_version", "") or ""),
            coverage_state=_parse_coverage_rows(section_text["## Coverage state"]),
            priority_queue=[],
            cycle_focus=cycle_focus,
            cycle_quota=int(fm.get("cycle_quota", 0) or 0),
            exclusions=_parse_exclusion_bullets(section_text["## Exclusions"]),
            narrative_header=narrative_header,
        )


def _parse_coverage_rows(section: str) -> list[CategoryFillState]:
    """Rows of the ``## Coverage state`` table, as ``to_markdown`` writes them.

    The header, the separator and any row whose numeric cells do not parse
    (the contract's example has a ``| ...`` filler) are skipped.
    """
    rows: list[CategoryFillState] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        try:
            target, met, priority = int(cells[1]), int(cells[2]), int(cells[4])
            fill_pct = int(cells[3].rstrip("%")) / 100
        except ValueError:
            continue
        topics = "|".join(cells[5:]).strip()
        rows.append(
            CategoryFillState(
                name=cells[0],
                target_count=target,
                met_count=met,
                fill_pct=fill_pct,
                priority=priority,
                unmet_topics=(
                    []
                    if topics in ("", "—")
                    else [t.strip() for t in topics.split(", ") if t.strip()]
                ),
            )
        )
    return rows


def _parse_exclusion_bullets(section: str) -> list[str]:
    """Bullets of ``## Exclusions``, without the ``- (none)`` placeholder.

    Stops at the next heading: the contract allows new sections after
    ``## Exclusions``, and their bullets are not exclusions.
    """
    exclusions: list[str] = []
    for raw in section.splitlines():
        if raw.startswith("## "):
            break
        line = raw.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if item and item != "(none)":
            exclusions.append(item)
    return exclusions


# ---------------------------------------------------------------------------
# Plan generation
# ---------------------------------------------------------------------------


def generate_plan(
    vault_dir: Path,
    spec: SpecConfig,
    cycle_number: int,
    *,
    require_nonempty_queue: bool = False,
) -> ResearchPlan:
    """Build the deterministic plan for ``cycle_number``.

    Pure function over filesystem state — calling it twice with the same
    inputs yields equal `ResearchPlan` instances (modulo
    ``generated_at``).

    The queue can legitimately be empty at pre-cycle generation time
    when the spec doesn't enumerate ``expected_filenames`` for its
    categories: scout's ``topics_found.new`` is merged in afterwards via
    :func:`merge_scout_topics`. Callers that want the v0.2.20 "fail
    closed at plan generation" semantics can pass
    ``require_nonempty_queue=True`` (used by the standalone
    ``research-framework plan`` CLI, where there is no scout step to
    enrich the queue downstream).

    Raises:
        ValueError: when ``cycle_number < 1``, or when
            ``require_nonempty_queue=True`` and the queue has fewer
            assignable topics than ``cycle_quota``.
    """
    if cycle_number < 1:
        raise ValueError(f"cycle_number must be >= 1, got {cycle_number}")

    # A run is a request for MORE. If every target is already met, the plan
    # would otherwise compute a remaining of zero, fall back to a quota of 1,
    # and spend the cycle re-treading a vault its own operator asked to grow.
    # Raise the bar first, then plan against it. No-op unless the vault opts in
    # with pipeline.coverage_growth > 1.0, and never for an archived vault.
    try:
        _vs = load_vault_settings(vault_dir)
        grow_targets_if_met(
            vault_dir,
            growth=_vs.coverage_growth,
            cap=_vs.coverage_growth_cap,
            archived=_vs.archived,
        )
    except SettingsError:
        # An unreadable settings file must not stop a cycle planning; the vault
        # simply does not grow this round, which is the pre-existing behaviour.
        pass
    targets = load_targets(vault_dir)

    coverage_state = _build_coverage_state(targets, vault_dir)
    # Spec 061: the cycle horizon comes from the vault settings
    # (canonical pipeline.max_cycles), not the (now-removed) spec field.
    max_cycles = effective_max_cycles(vault_dir)
    cycle_quota = _compute_cycle_quota(targets, cycle_number, max_cycles)
    cycle_focus = _select_cycle_focus(coverage_state)
    exclusions = _build_exclusions(vault_dir, spec)
    priority_queue = _build_priority_queue(vault_dir, spec, coverage_state, exclusions)

    if require_nonempty_queue and len(priority_queue) < cycle_quota:
        raise ValueError(
            "insufficient priority queue: have "
            f"{len(priority_queue)} topic(s) but cycle_quota={cycle_quota}. "
            "Either narrow coverage_targets, add data_sources, "
            "or raise pipeline.max_cycles in settings.yaml (or pass --max-cycles)."
        )

    return ResearchPlan(
        cycle_number=cycle_number,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        framework_version=str(_FRAMEWORK_VERSION),
        coverage_state=coverage_state,
        priority_queue=priority_queue,
        cycle_focus=cycle_focus,
        cycle_quota=cycle_quota,
        exclusions=exclusions,
        narrative_header="",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_coverage_state(
    targets: CoverageTargets, vault_dir: Path
) -> list[CategoryFillState]:
    """One ``CategoryFillState`` per category in declaration order.

    ``unmet_topics`` is populated from ``expected_filenames`` minus the
    files already on disk — the same dedup the scout would do (mirrors
    ``coverage.unmet_expected_filenames`` but inlined here so we don't
    re-walk the vault per category).
    """
    existing = set(existing_vault_filenames(vault_dir))
    out: list[CategoryFillState] = []
    for c in targets.categories:
        fill = min(1.0, c.met_count / c.target_count) if c.target_count > 0 else 1.0
        unmet_topics = [f for f in c.expected_filenames if f not in existing]
        out.append(
            CategoryFillState(
                name=c.name,
                target_count=c.target_count,
                met_count=c.met_count,
                fill_pct=fill,
                priority=int(c.priority),
                unmet_topics=unmet_topics,
            )
        )
    return out


def _compute_cycle_quota(
    targets: CoverageTargets, cycle_number: int, max_cycles: int
) -> int:
    """``ceil(remaining / remaining_cycles)`` per FR-017."""
    remaining = sum(max(0, c.target_count - c.met_count) for c in targets.categories)
    if remaining <= 0:
        return 1
    remaining_cycles = max(1, max_cycles - (cycle_number - 1))
    return max(1, math.ceil(remaining / remaining_cycles))


def _select_cycle_focus(
    coverage_state: list[CategoryFillState],
) -> list[str]:
    """Top-3 lowest-fill categories among ``priority >= 50`` unmet rows.

    Falls back to all unmet categories sorted the same way when no
    high-priority unmet rows exist (so the data-model invariant
    ``len(cycle_focus) >= 1`` holds whenever any work remains).
    """
    unmet = [c for c in coverage_state if c.met_count < c.target_count]
    if not unmet:
        return []
    high = [c for c in unmet if c.priority >= _HIGH_PRIORITY_THRESHOLD]
    pool = high if high else unmet
    pool_sorted = sorted(pool, key=lambda c: (c.fill_pct, -c.priority, c.name))
    return [c.name for c in pool_sorted[:3]]


def _normalize_exclusion_key(name: str) -> str:
    """Canonical key for dedup across already-covered / rejects /
    out-of-scope. Strips a trailing ``.md`` and lowercases."""
    n = name.strip().lower()
    if n.endswith(".md"):
        n = n[:-3]
    return n


def _exclusion_slug(name: str) -> str:
    """:func:`_normalize_exclusion_key` with each run of non-word characters
    turned into one ``-``.

    A scout row is checked by its filename or, without one, its title; an
    exclusion is a file stem (``full_name`` or ``slug`` convention) or a spec
    phrase. ``Vendor Pricing``, ``vendor-pricing.md`` and ``vendor pricing``
    name the same topic and only compare equal in this form.
    """
    return re.sub(r"[\W_]+", "-", _normalize_exclusion_key(name)).strip("-")


def _build_exclusions(vault_dir: Path, spec: SpecConfig) -> list[str]:
    """Bullet-line strings in priority order:

    ``already-covered`` → ``persistent-rejects`` → ``out-of-scope``.

    Dedup is done on the canonical key (lowercase stem, ``.md``
    stripped) so a vault file ``foo.md`` collides with both a reject of
    ``foo.md`` and an out-of-scope entry ``foo``. The first source to
    claim a key wins — matches the contract's intent that
    "already-covered" is the most informative label when a name appears
    in multiple lists.
    """
    seen: set[str] = set()
    out: list[str] = []

    for name in existing_vault_filenames(vault_dir):
        key = _normalize_exclusion_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(f"already-covered: {key}")

    rejects_path = vault_dir / "_pipeline" / "rejects.json"
    if rejects_path.is_file():
        try:
            data = json.loads(rejects_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for entry in (data or {}).get("rejects", []) or []:
            if not isinstance(entry, dict):
                continue
            try:
                count = int(entry.get("reject_count", 0) or 0)
            except (TypeError, ValueError):
                continue
            if count < _PERSISTENT_REJECT_THRESHOLD:
                continue
            name = str(entry.get("proposed_filename", "") or "")
            key = _normalize_exclusion_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(f"persistent-rejects: {key}")

    for name in spec.scope.out_of_scope or []:
        key = _normalize_exclusion_key(str(name))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(f"out-of-scope: {key}")

    return out


def _orphan_score(citation_count: int) -> float:
    """``min(1.0, 0.3 + 0.1 * count)`` per R-009."""
    return min(1.0, 0.3 + 0.1 * max(0, int(citation_count)))


def _spec_gap_score(priority: int, fill_gap: float) -> float:
    """Normalised ``[0.0, 1.0]`` score for a spec-gap topic.

    ``priority`` is treated as a ``[0, 100]`` scale (validator enforces
    the bound; we clamp defensively). ``fill_gap`` is the unfilled
    fraction (``1 - met/target``). The product preserves the ranking
    intent ("higher priority and emptier categories first") on a scale
    comparable with orphan scores.
    """
    p = max(0, min(100, int(priority)))
    g = max(0.0, min(1.0, float(fill_gap)))
    return (p / 100.0) * g


def _parse_orphans(vault_dir: Path) -> list[tuple[str, int]]:
    """Return ``(title, citation_count)`` per unique orphan in the
    backlog, oldest blocks first.

    Title comparison is case-insensitive so two cycles citing the same
    orphan with different casing still collapse to one queue entry.
    """
    path = vault_dir / "_pipeline" / "research-backlog.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    seen: set[str] = set()
    out: list[tuple[str, int]] = []
    for match in _ORPHAN_BULLET_RE.finditer(text):
        title = match.group(1).strip()
        try:
            count = int(match.group(2))
        except ValueError:
            continue
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        out.append((title, count))
    return out


PLACEHOLDER_PROVENANCE = "spec_gap_placeholder"
"""Distinct provenance for ``_placeholder_titles`` stubs so the batch dispatcher
can drop them before they reach a note-writer agent. Real ``spec_gap`` topics
(from ``CategoryFillState.unmet_topics`` — enumerated by the spec) keep
``provenance="spec_gap"`` and ARE valid research targets."""

PLACEHOLDER_TITLE_RE = re.compile(r":\s*focus topic\s+\d+\s*$", re.IGNORECASE)
"""Regex matching the literal output of ``_placeholder_titles``. Used by the
batch layer as a belt-and-suspenders second check in case provenance gets
lost during serialization round-trips (the v0.2.19 cycle-6 crash hit when
``cycle-006-batch-009-dfs.md`` was handed four ``"flows: focus topic 3"``-
style titles and the writer agent — correctly — refused to invent research
for them)."""


def is_placeholder_topic(topic: object) -> bool:
    """Return True if ``topic`` (PrioritizedTopic or dict) is a placeholder stub.

    Checks ``provenance == PLACEHOLDER_PROVENANCE`` first, then falls back to
    a regex on the title in case the topic was reloaded from a serialized
    batch report that pre-dates the provenance tag.
    """
    if isinstance(topic, dict):
        prov = topic.get("provenance")
        title = topic.get("title", "")
    else:
        prov = getattr(topic, "provenance", None)
        title = getattr(topic, "title", "")
    if prov == PLACEHOLDER_PROVENANCE:
        return True
    return bool(isinstance(title, str) and PLACEHOLDER_TITLE_RE.search(title))


def _placeholder_titles(category_name: str, display_name: str, gap: int) -> list[str]:
    """Generate up to ``min(gap, _MAX_PLACEHOLDERS_PER_CATEGORY)``
    placeholder topic titles for a category whose ``expected_filenames``
    are not enumerated by the spec.

    The placeholders are deliberately generic — the scout was originally
    supposed to enrich them with concrete titles from the sources during
    the cycle. In practice that round-trip is unreliable; if a placeholder
    survives to the note-writer it can't be researched (no concrete topic
    to research) and the cycle aborts via SG-005. They are kept here so
    the ``insufficient queue`` guard still trips for over-promised specs,
    but the batch dispatcher filters them before invocation — see
    :data:`PLACEHOLDER_PROVENANCE` and the ``slice_topics_into_batches``
    filter in ``pipeline/batch.py``.
    """
    count = min(max(0, int(gap)), _MAX_PLACEHOLDERS_PER_CATEGORY)
    label = display_name or category_name
    return [f"{label}: focus topic {i + 1}" for i in range(count)]


def _build_priority_queue(
    vault_dir: Path,
    spec: SpecConfig,
    coverage_state: list[CategoryFillState],
    exclusions: list[str],
) -> list[PrioritizedTopic]:
    """Combine spec-gap + orphan topics, drop excluded titles, sort
    descending by ``priority_score``."""
    excluded_keys = {
        _normalize_exclusion_key(line.split(": ", 1)[-1]) for line in exclusions
    }

    queue: list[PrioritizedTopic] = []

    for state in coverage_state:
        gap = state.target_count - state.met_count
        if gap <= 0:
            continue
        fill_gap = 1.0 - state.fill_pct
        score = _spec_gap_score(state.priority, fill_gap)
        # Only emit topics for categories whose `expected_filenames` were
        # enumerated by the spec author. Categories with no enumeration
        # depend entirely on scout discovery — they contribute zero rows
        # here and pick up real topics via `merge_scout_topics` between
        # Step 1 (scout) and Step 3 (DFS dispatch) in the cycle runner.
        # The historical fallback (`_placeholder_titles` synthesising
        # "flows: focus topic N") was removed in v0.2.21 because those
        # stubs reliably yielded zero-note batches and triggered the
        # SG-005 correction directive, which the v0.2.19 cycle-6 trace
        # showed was the entry point for "bookkeeping fraud" (cosmetic
        # frontmatter edits masquerading as research output).
        unmet = state.unmet_topics
        if not unmet:
            continue
        for title in unmet:
            if _normalize_exclusion_key(title) in excluded_keys:
                continue
            queue.append(
                PrioritizedTopic(
                    title=title,
                    category=state.name,
                    priority_score=score,
                    source_hints=[],
                    provenance="spec_gap",
                    citation_count=0,
                )
            )

    orphan_category = _pick_orphan_category(coverage_state)
    for title, count in _parse_orphans(vault_dir):
        if _normalize_exclusion_key(title) in excluded_keys:
            continue
        queue.append(
            PrioritizedTopic(
                title=title,
                category=orphan_category,
                priority_score=_orphan_score(count),
                source_hints=[],
                provenance="harvest_orphan",
                citation_count=int(count),
            )
        )

    queue.sort(key=lambda t: (-t.priority_score, t.category, t.title))
    return queue


SCOUT_PROVENANCE = "scout"
"""Provenance tag for topics merged from ``cycle-NNN-scout.json`` post
Step 1. Distinguishes them from ``spec_gap`` (statically enumerated by
the spec author) and ``harvest_orphan`` (surfaced by previous cycles'
wikilink harvesting). The batch filter treats ``SCOUT_PROVENANCE`` as
real research material — it is the primary path to non-empty cycles
since v0.2.21 dropped synthetic placeholder generation."""

_SCOUT_PRIORITY_SCORE = 1.0
"""Scout-derived topics are pinned at the top of the priority queue.

Rationale: a topic the scout *just* surfaced from a live source
(local code, PR history, internal migration notes, docs) has the
strongest available signal that it (a) actually exists, (b) is
relevant to the spec's scope, and (c) has at least one citable source
on disk. Spec-gap rows and stale orphan backlogs both lag the world by
at least one cycle. Capping at ``1.0`` keeps the existing
``[0.0, 1.0]`` priority-score contract intact."""


def merge_scout_topics(
    plan: ResearchPlan,
    scout_report_path: Path,
    *,
    exclude_existing_titles: bool = True,
) -> ResearchPlan:
    """Return a new ``ResearchPlan`` with scout-discovered topics prepended.

    Reads ``cycle-NNN-scout.json`` and converts every entry in
    ``topics_found.new`` into a :class:`PrioritizedTopic` carrying
    ``provenance=SCOUT_PROVENANCE`` and ``priority_score=
    _SCOUT_PRIORITY_SCORE``. The resulting queue is then re-sorted by
    the existing ``(-score, category, title)`` rule so scout topics
    cluster at the top, with spec-gap and orphan rows beneath.

    Best-effort:

    - missing scout report → plan returned unchanged (logged once at
      INFO level so the cycle log shows why the queue stayed thin);
    - malformed JSON or missing keys → unchanged + WARN log;
    - individual topic entries without a ``title`` are skipped
      silently; the rest still merge.

    Dedup against the plan's existing queue (case-insensitive title
    match) is on by default so a scout topic that already matches a
    spec-gap row doesn't end up twice in the dispatcher. Pass
    ``exclude_existing_titles=False`` only when the caller has its own
    dedup pass downstream.
    """
    if not scout_report_path.is_file():
        _LOG.info(
            "merge_scout_topics: %s not present — plan unchanged", scout_report_path
        )
        return plan

    try:
        doc = json.loads(scout_report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning(
            "merge_scout_topics: could not read %s: %s — plan unchanged",
            scout_report_path,
            exc,
        )
        return plan

    if not isinstance(doc, dict):
        _LOG.warning(
            "merge_scout_topics: %s did not parse to a dict — plan unchanged",
            scout_report_path,
        )
        return plan

    found = doc.get("topics_found")
    if not isinstance(found, dict):
        return plan
    raw_new = found.get("new") or []
    if not isinstance(raw_new, list):
        return plan

    seen_titles: set[str] = (
        {t.title.strip().casefold() for t in plan.priority_queue if t.title.strip()}
        if exclude_existing_titles
        else set()
    )
    excluded_keys = {_exclusion_slug(e.split(": ", 1)[-1]) for e in plan.exclusions}

    scout_topics: list[PrioritizedTopic] = []
    for entry in raw_new:
        # normalise_topic_row (shared with gates_step._topics_found_new_rows)
        # tolerates bare-string rows emitted by minimal scout outputs
        # (e.g. codex/gpt baseline mode) by wrapping them as {"title": ...}.
        entry = normalise_topic_row(entry)
        if entry is None:
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        cf = title.casefold()
        if cf in seen_titles:
            continue
        # Drop scout topics that the spec author already marked
        # out-of-scope or whose filename collides with an already-covered
        # note. Without this the dispatcher would still skip them at
        # batch time, but the rendered plan would mislead a human
        # reader by promising work that can't happen.
        category = str(
            entry.get("coverage_category")
            or entry.get("category")
            or _pick_orphan_category(plan.coverage_state)
        )
        proposed = str(entry.get("proposed_filename") or "")
        check_key = _exclusion_slug(proposed) or _exclusion_slug(title)
        if check_key and check_key in excluded_keys:
            continue
        source_hints: list[str] = []
        for key in ("source_code_topic_ids", "source_intent_ids", "source_urls"):
            v = entry.get(key)
            if isinstance(v, list):
                source_hints.extend(str(x) for x in v if str(x).strip())
        scout_topics.append(
            PrioritizedTopic(
                title=title,
                category=category,
                priority_score=_SCOUT_PRIORITY_SCORE,
                source_hints=source_hints,
                provenance=SCOUT_PROVENANCE,
                citation_count=0,
            )
        )
        seen_titles.add(cf)

    if not scout_topics:
        return plan

    merged_queue = scout_topics + list(plan.priority_queue)
    merged_queue.sort(key=lambda t: (-t.priority_score, t.category, t.title))

    import dataclasses as _dc

    return _dc.replace(plan, priority_queue=merged_queue)


def _pick_orphan_category(coverage_state: list[CategoryFillState]) -> str:
    """R-009 puts orphans under category ``concept`` by default. Fall
    back to the first declared category when the spec doesn't have one
    (so the queue entry still references a real coverage row)."""
    for c in coverage_state:
        if c.name == "concept":
            return c.name
    return coverage_state[0].name if coverage_state else "concept"


def _atomic_write_text(path: Path, content: str) -> None:
    from .atomic_write import write_text

    write_text(path, content)


def main(argv: list[str] | None = None) -> int:
    """CLI for T018: write deterministic ``_pipeline/research-plan.md`` and archive.

    Exit ``0`` on success, ``2`` on structural errors (missing files, bad JSON,
    invalid spec, or ``generate_plan`` preconditions unmet).
    """
    import argparse
    import sys

    from ..spec.parser import parse

    parser = argparse.ArgumentParser(
        description="Generate deterministic research-plan.md for a vault cycle.",
    )
    parser.add_argument(
        "vault_dir",
        type=Path,
        help="Path to the vault root directory",
    )
    parser.add_argument(
        "--cycle",
        type=int,
        required=True,
        metavar="N",
        help="Cycle number (integer >= 1)",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Path to research.spec.md (default: <vault_dir>/research.spec.md)",
    )
    ns = parser.parse_args(argv)
    if ns.cycle < 1:
        print("error: --cycle must be >= 1", file=sys.stderr)  # noqa: T201 — keep raw print: CLI usage error
        return 2

    vault_dir = ns.vault_dir.expanduser().resolve()
    spec_path = (
        (ns.spec if ns.spec is not None else vault_dir / "research.spec.md")
        .expanduser()
        .resolve()
    )

    try:
        spec = parse(spec_path)
        plan = generate_plan(vault_dir, spec, ns.cycle)
        body = plan.to_markdown()
    except (
        FileNotFoundError,
        SpecValidationError,
        ValueError,
        RuntimeError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)  # noqa: T201 — keep raw print: CLI usage error
        return 2

    out_live = vault_dir / "_pipeline" / "research-plan.md"
    out_archive = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{ns.cycle:03d}-research-plan.md"
    )
    try:
        _atomic_write_text(out_live, body)
        _atomic_write_text(out_archive, body)
    except OSError as exc:
        print(str(exc), file=sys.stderr)  # noqa: T201 — keep raw print: CLI usage error
        return 2
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
