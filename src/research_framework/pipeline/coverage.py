"""Coverage target I/O and queries.

Reads/writes `{vault}/_pipeline/coverage-targets.json` with atomic file replacement.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

from ..spec.schema import CoverageCategory, CoverageTargets
from .atomic_write import write_json
from .settings import CycleYieldSettings, SettingsError, load_vault_settings

_LOG = logging.getLogger(__name__)

TARGETS_REL = Path("_pipeline") / "coverage-targets.json"

# Strips a leading "NN - " scaffold ordering prefix from a category directory
# name (e.g. "01 - Concepts" -> "Concepts") so it can be matched against a
# category's slug / display_name for the frontmatter-vs-directory check (D5).
_DIR_PREFIX_RE = re.compile(r"^\s*\d+\s*[-–]\s*")

# Very small English + Portuguese stopword set used by the fallback keyword
# classifier. Kept inline (not a dependency) to preserve the "Python 3.11+
# stdlib only" promise from the constitution. Additions welcome — the classifier
# is a safety net, not a linguist. See ``classify_note_category``.
_CATEGORY_STOPWORDS = frozenset(
    {
        # english
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
        "about",
        "after",
        "all",
        "any",
        "can",
        "do",
        "etc",
        "had",
        "has",
        "have",
        "how",
        "if",
        "not",
        "out",
        "per",
        "some",
        "such",
        "than",
        "then",
        "they",
        "these",
        "those",
        "via",
        "what",
        "when",
        "where",
        "who",
        "why",
        "you",
        "your",
        "other",
        "more",
        "over",
        "under",
        "also",
        # portuguese
        "de",
        "do",
        "da",
        "dos",
        "das",
        "e",
        "é",
        "em",
        "um",
        "uma",
        "uns",
        "umas",
        "para",
        "por",
        "com",
        "sem",
        "que",
        "se",
        "ao",
        "à",
        "aos",
        "às",
        "no",
        "na",
        "nos",
        "nas",
        "os",
        "as",
        "seu",
        "sua",
        "seus",
        "suas",
        "pela",
        "pelo",
        "pelas",
        "pelos",
        "mas",
        "ou",
        "ainda",
        "apenas",
    }
)
_CATEGORY_TOKEN_MIN_LEN = 4
_CATEGORY_TOKEN_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9]+")


def _targets_path(vault_dir: Path) -> Path:
    return vault_dir / TARGETS_REL


def load_targets(vault_dir: Path) -> CoverageTargets:
    path = _targets_path(vault_dir)
    if not path.exists():
        raise FileNotFoundError(f"coverage-targets.json not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"coverage-targets.json is malformed: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("coverage-targets.json is not an object")
    return CoverageTargets.from_dict(data)


def save_targets(vault_dir: Path, targets: CoverageTargets) -> None:
    write_json(_targets_path(vault_dir), targets.to_dict())


# Default multiplier for the growth step below. 1.0 keeps a vault one-and-done,
# which is right for one that answers a fixed question and then stops — a
# market snapshot, a "what are my options" vault. Above 1.0 says the vault is
# expected to keep pace with a subject that moves.
DEFAULT_COVERAGE_GROWTH = 1.0

# Ceiling on what ONE category may gain in ONE round. A bare multiplier is
# compound interest: at 1.4 a 143-note target becomes 200, 280, 392, 549 in
# four rounds, and the bar outruns anything an operator would actually write —
# which puts the vault permanently unmet and makes the Phase 3 gate useless in
# the other direction. The cap makes growth multiplicative while a category is
# small (where a percentage is the sensible unit) and linear once it is large
# (where a percentage is absurd), which is the shape people mean by
# "exponential" when they do not mean it literally.
DEFAULT_COVERAGE_GROWTH_CAP = 10


def grow_targets_if_met(
    vault_dir: Path,
    *,
    growth: float | None = None,
    cap: int | None = None,
    archived: bool = False,
) -> tuple[bool, int, int]:
    """Raise every target by the growth factor once the vault has met them all.

    ``target_count`` was read as a LIFETIME ceiling, so a vault that reached it
    was finished forever. A 441-note vault carrying a 55-note target computed
    its remaining work as one note and planned a ``cycle_quota`` of 2 — while
    its own scout surfaced current material the plan then discarded for not
    belonging to an unmet category. The target was only ever meant to say
    "this much, for now".

    Why the raise fires HERE, on met, and not continuously: a target recomputed
    from ``met_count`` on every plan recedes as the vault approaches it, so the
    Phase 3 gate can never close and "coverage met" stops meaning anything.
    Freezing it to the moment everything is met keeps each round finite and
    reachable, and still compounds — each round multiplies a larger base, so
    growth is exponential across rounds rather than a constant increment.

    The raise is capped per category per round (``cap``), so the shape is
    multiplicative while a category is small and linear once it is large. An
    uncapped multiplier compounds: 1.4 turns a 143-note target into 549 in four
    rounds, which no operator writes, and a permanently-unmet vault is as
    useless as a permanently-finished one.

    Archived vaults are never grown: spec 071's flag means finished, and an
    operator who archived a vault did not ask for more of it.

    Returns ``(grown, old_total, new_total)``. ``grown`` is False when the vault
    still has work, is archived, or the factor is at or below 1.0.
    """
    factor = DEFAULT_COVERAGE_GROWTH if growth is None else float(growth)
    per_round_cap = DEFAULT_COVERAGE_GROWTH_CAP if cap is None else int(cap)
    targets = load_targets(vault_dir)
    old_total = sum(c.target_count for c in targets.categories)
    if archived or factor <= 1.0 or not targets.categories:
        return False, old_total, old_total
    if any(not c.is_met for c in targets.categories):
        return False, old_total, old_total
    for c in targets.categories:
        # Always at least one more (a category at a target of 1 must not
        # multiply to itself and stall the vault), never more than the cap.
        grown_to = min(math.ceil(c.met_count * factor), c.met_count + per_round_cap)
        c.target_count = max(c.target_count + 1, grown_to)
    save_targets(vault_dir, targets)
    new_total = sum(c.target_count for c in targets.categories)
    _LOG.info(
        "[coverage] all targets met - grown x%.2f (cap +%d/category): "
        "%d -> %d across %d categories",
        factor,
        per_round_cap,
        old_total,
        new_total,
        len(targets.categories),
    )
    return True, old_total, new_total


def _category_tokens(text: str) -> set[str]:
    """Tokenise ``text`` into a set of lowercase keywords for classification.

    Strips stopwords, collapses accents-agnostic tokens, and drops tokens
    shorter than ``_CATEGORY_TOKEN_MIN_LEN``. Deliberately simple — the
    fallback classifier only has to discriminate between a handful of
    categories per vault, not index the web.
    """
    tokens = {t.lower() for t in _CATEGORY_TOKEN_RE.findall(text or "")}
    return {
        t
        for t in tokens
        if len(t) >= _CATEGORY_TOKEN_MIN_LEN and t not in _CATEGORY_STOPWORDS
    }


def classify_note_category(
    frontmatter: dict,
    filename: str,
    categories: list[CoverageCategory],
) -> CoverageCategory | None:
    """Pick ONE category for a note.

    Resolution order:

    1. Explicit: ``frontmatter.coverage_category`` matches a category ``name``
       or a category ``display_name`` (case-insensitive). This is the path
       the DFS agent takes when it follows the prompt.
    2. Keyword overlap: tokens extracted from the note's title/summary/tags/
       filename are intersected with tokens from each category's
       ``display_name``; the category with the highest overlap wins. Ties
       break toward the category with the largest remaining ``gap`` so
       coverage naturally spreads.
    3. Round-robin on gap: when there's zero keyword signal, return the
       required category with the biggest unmet gap. Guarantees the note
       makes forward progress somewhere — the whole point of this module
       after the v0.2.11 "every concept counts everywhere" regression.

    Returns ``None`` only when the category list itself is empty — in that
    case the caller should skip the increment.
    """
    if not categories:
        return None

    # 1. Explicit frontmatter assignment.
    explicit = str((frontmatter or {}).get("coverage_category", "") or "").strip()
    if explicit:
        for cat in categories:
            if cat.name.lower() == explicit.lower():
                return cat
            if cat.display_name and cat.display_name.lower() == explicit.lower():
                return cat
        # Unknown slug falls through to the content classifier; it's better
        # to try and misclassify than silently drop the note.

    # 2. Keyword overlap against display_name.
    haystack_parts = [
        str((frontmatter or {}).get("title", "") or ""),
        str((frontmatter or {}).get("summary", "") or ""),
        " ".join(str(t) for t in (frontmatter or {}).get("tags", []) or [] if t),
        Path(filename).stem.replace("_", " ").replace("-", " "),
    ]
    note_tokens = _category_tokens(" ".join(haystack_parts))

    best: tuple[int, int, CoverageCategory] | None = None
    for cat in categories:
        cat_tokens = _category_tokens(cat.display_name or cat.name)
        overlap = len(note_tokens & cat_tokens)
        if overlap == 0:
            continue
        # gap acts as tiebreaker — prefer under-met categories when scores tie.
        score = (overlap, cat.gap)
        if best is None or score > (best[0], best[1]):
            best = (overlap, cat.gap, cat)
    if best is not None:
        return best[2]

    # 3. Round-robin by largest gap among required categories. Filter to
    # ``required`` so optional categories don't soak up notes meant for the
    # mandatory ones. If everything is met, the first category still gets
    # the bump so the file stays accurate.
    required = [c for c in categories if c.required] or list(categories)
    required.sort(key=lambda c: (-c.gap, c.name))
    return required[0]


def _existing_category_dirs(vault_dir: Path) -> list[Path]:
    data_vault = corpus_dir(vault_dir)
    if not data_vault.is_dir():
        return []
    return [
        d
        for d in sorted(data_vault.iterdir())
        if d.is_dir() and not d.name.startswith("_")
    ]


def _category_labels(category: CoverageCategory) -> set[str]:
    labels = {category.name.strip().lower()}
    if category.display_name:
        labels.add(category.display_name.strip().lower())
    return {label for label in labels if label}


def resolve_category_folder(vault_dir: Path, frontmatter: dict) -> Path:
    """Resolve the ``data_vault/`` destination directory for a reinstated note (066 D7).

    Quarantine flattens the original category path, so re-derive it from the
    note's ``coverage_category``: match against existing
    ``data_vault/<NN - DisplayName>/`` directories (∪ the spec's
    ``coverage_targets`` display-name hints), falling back to the keyword
    classifier and finally the ``data_vault`` root. The returned directory is
    NOT created here — the caller (``cli/regrade``) ensures it exists before the
    move.
    """
    data_vault = corpus_dir(vault_dir)
    existing = _existing_category_dirs(vault_dir)
    explicit = str((frontmatter or {}).get("coverage_category", "") or "").strip()

    try:
        categories = load_targets(vault_dir).categories
    except (FileNotFoundError, RuntimeError):
        categories = []

    def _match_dir(*labels: str) -> Path | None:
        wanted = {label.strip().lower() for label in labels if label and label.strip()}
        for directory in existing:
            dir_label = _DIR_PREFIX_RE.sub("", directory.name).strip().lower()
            if dir_label in wanted:
                return directory
        return None

    # 1. explicit coverage_category → existing dir (direct, then via category).
    if explicit:
        hit = _match_dir(explicit)
        if hit is not None:
            return hit
        for cat in categories:
            if explicit.lower() in _category_labels(cat):
                hit = _match_dir(cat.name, cat.display_name)
                if hit is not None:
                    return hit

    # 2. keyword classifier → category → existing dir.
    classified = classify_note_category(frontmatter or {}, "", categories)
    if classified is not None:
        hit = _match_dir(classified.name, classified.display_name)
        if hit is not None:
            return hit
        label = (classified.display_name or classified.name).strip()
        if label:
            return data_vault / label

    # 3. last resort: data_vault root (caller still moves the note into the corpus).
    return data_vault


def _dir_implied_category_name(
    note_path: Path, categories: list[CoverageCategory]
) -> str | None:
    """Best-effort: map a note's parent directory to a category ``name``.

    The scaffold lays notes out under ``data_vault/NN - Title/`` directories
    where ``Title`` mirrors a category slug or ``display_name``. Strips the
    ``NN - `` ordering prefix and matches case-insensitively against each
    category's ``name`` and ``display_name``. Returns the matched category
    ``name`` or ``None`` when the directory doesn't map to any category — the
    common case for vaults that don't use the numbered-directory convention.
    Used only for the FR1 frontmatter-vs-directory disagreement WARN (D5);
    never to assign a category.
    """
    label = _DIR_PREFIX_RE.sub("", note_path.parent.name).strip().lower()
    if not label:
        return None
    for cat in categories:
        if cat.name.lower() == label:
            return cat.name
        if cat.display_name and cat.display_name.lower() == label:
            return cat.name
    return None


def recompute_from_disk(vault_dir: Path, *, persist: bool = True) -> CoverageTargets:
    """Recompute every category's ``met_count`` from the on-disk notes (068 FR1).

    Walks ``data_vault/**/*.md``, parses each note's frontmatter, and assigns it
    to exactly one coverage category via the existing
    :func:`classify_note_category` (explicit ``coverage_category`` wins, keyword
    overlap is the fallback, largest-gap round-robin is the last resort). This
    replaces the legacy per-cycle *increment* model — which accumulated
    ``met_count`` from each cycle's ``notes_created`` list and drifted out of
    sync with the tree (the rc7 ``0% → 0%`` bug) — with a deterministic full
    recount that is the single source of truth.

    Rules:

    * ``met_count`` is reset to 0 before counting (full recount, not increment).
    * ``note_type: alias`` stubs are skipped (spec-062 FR3).
    * Only categories whose ``note_type`` equals the note's ``type`` are
      eligible, so a ``source`` note can't satisfy a ``concept`` category.
    * Frontmatter ``coverage_category`` wins over the directory; a disagreement
      is logged WARN, never silently re-bucketed by directory (D5).

    Pure + idempotent w.r.t. the tree: same ``data_vault/`` ⇒ same counts.
    When ``persist`` is True the recount is written back to
    ``coverage-targets.json`` via the existing atomic :func:`save_targets`
    (a cache write); read-only consumers (e.g. ``vault status``) pass
    ``persist=False``.
    """
    targets = load_targets(vault_dir)
    for cat in targets.categories:
        cat.met_count = 0

    data_vault = corpus_dir(vault_dir)
    if data_vault.is_dir():
        for note in sorted(data_vault.rglob("*.md")):
            try:
                fm, _body = parse_frontmatter(note)
            except (OSError, FrontmatterParseError):
                continue
            if not fm:
                continue
            if str((fm or {}).get("note_type", "") or "").strip().lower() == "alias":
                continue
            ntype = str((fm or {}).get("type", "") or "").strip()
            if not ntype:
                continue
            eligible = [c for c in targets.categories if c.note_type == ntype]
            chosen = classify_note_category(fm, note.name, eligible)
            if chosen is None:
                continue
            chosen.met_count += 1
            explicit = str((fm or {}).get("coverage_category", "") or "").strip()
            if explicit:
                dir_cat = _dir_implied_category_name(note, eligible)
                if dir_cat is not None and dir_cat != chosen.name:
                    _LOG.warning(
                        "coverage: %s declares coverage_category=%r (→ %s) but lives "
                        "in directory implying %r — frontmatter wins (068 D5)",
                        note.name,
                        explicit,
                        chosen.name,
                        dir_cat,
                    )

    if persist:
        save_targets(vault_dir, targets)
    return targets


def _eligible_created_count(vault_dir: Path, research_report: dict) -> int | None:
    """Count this cycle's ``notes_created`` that are countable toward coverage.

    A note is countable when it resolves on disk, is not an ``alias`` stub, has
    a non-empty ``type``, and at least one category shares that ``type``. Used
    by the FR2 invariant to cross-check the disk recount against the cycle's
    expected increment. Returns ``None`` when no usable report list is present.
    """
    created = research_report.get("notes_created")
    if created is None:
        return None
    try:
        targets = load_targets(vault_dir)
    except (FileNotFoundError, RuntimeError):
        return None
    types_with_targets = {c.note_type for c in targets.categories}
    data_vault = corpus_dir(vault_dir)
    count = 0
    for name in created:
        basename = Path(str(name)).name
        matches = list(data_vault.rglob(basename)) if data_vault.is_dir() else []
        if not matches:
            continue
        try:
            fm, _body = parse_frontmatter(matches[0])
        except (OSError, FrontmatterParseError):
            continue
        if not fm:
            continue
        if str((fm or {}).get("note_type", "") or "").strip().lower() == "alias":
            continue
        ntype = str((fm or {}).get("type", "") or "").strip()
        if not ntype or ntype not in types_with_targets:
            continue
        count += 1
    return count


def update_after_cycle(
    vault_dir: Path, research_report: dict, cycle_number: int | None = None
) -> CoverageTargets:
    """Recompute coverage from disk at cycle-end and surface any divergence.

    Spec 068 (FR1/FR2): coverage is now a **derived-from-disk** quantity. This
    delegates to :func:`recompute_from_disk` (the single source of truth) and
    cross-checks the result against the incremental expectation — the previously
    stored ``met_count`` plus this cycle's countable ``notes_created``. When the
    two disagree (e.g. a stale rc7 vault self-healing, or notes that went
    missing), it logs a **loud WARN and trusts the recount** (WARN-and-trust,
    decided at /analyze U1 — never a hard ERROR/block).

    Prior behaviour (v0.2.11–rc7) incremented ``met_count`` from
    ``notes_created`` and never reconciled with the tree, so the stored count
    drifted below reality and the digest reported ``0% → 0%`` despite ~107
    notes on disk. ``research_report`` is retained for the invariant cross-check
    and signature compatibility.
    """
    prior_sum: int | None
    try:
        prior_sum = sum(max(0, c.met_count) for c in load_targets(vault_dir).categories)
    except (FileNotFoundError, RuntimeError):
        prior_sum = None
    new_count = _eligible_created_count(vault_dir, research_report)

    targets = recompute_from_disk(vault_dir, persist=False)
    recount_sum = sum(max(0, c.met_count) for c in targets.categories)

    if prior_sum is not None and new_count is not None:
        expected = prior_sum + new_count
        if expected != recount_sum:
            _LOG.warning(
                "coverage invariant divergence (068 FR2): incremental expectation "
                "%d (prior %d + %d created) != disk recount %d — trusting recount",
                expected,
                prior_sum,
                new_count,
                recount_sum,
            )

    targets.last_updated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if cycle_number is not None:
        targets.cycle_number = cycle_number

    save_targets(vault_dir, targets)
    return targets


def all_targets_met(vault_dir: Path) -> bool:
    return all(c.is_met for c in load_targets(vault_dir).categories)


def unmet_targets(vault_dir: Path) -> list[str]:
    return [c.name for c in load_targets(vault_dir).categories if not c.is_met]


# --- Feature 002: repo-scan-derived expected filenames ---

REPO_SCAN_REL = Path("_pipeline") / "repo-scan.json"
_CATEGORY_TO_SCAN_KEY = {
    "services": "services",
    "concepts": "concepts",
    "flows": "flows",
    "decisions": "decisions",
}


def merge_expected_filenames_from_scan(vault_dir: Path) -> CoverageTargets:
    """Populate `CoverageCategory.expected_filenames` from repo-scan.json.

    For categories whose `name` matches a key in the scan's `derived_targets`,
    the expected-filename list is copied in and `target_count` is bumped to
    `max(target_count, len(expected_filenames))`. Categories without a match
    are left untouched — soft types (market/team/...) continue to use the
    hand-typed target_count.

    Returns the updated CoverageTargets (also persisted to coverage-targets.json).
    """
    targets = load_targets(vault_dir)
    scan_path = vault_dir / REPO_SCAN_REL
    if not scan_path.exists():
        return targets
    try:
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return targets
    derived = scan.get("derived_targets") or {}
    if not isinstance(derived, dict):
        return targets

    for cat in targets.categories:
        scan_key = _CATEGORY_TO_SCAN_KEY.get(cat.name)
        if not scan_key:
            continue
        filenames = list(derived.get(scan_key, []) or [])
        if not filenames:
            continue
        cat.expected_filenames = filenames
        if cat.target_count < len(filenames):
            cat.target_count = len(filenames)

    targets.last_updated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_targets(vault_dir, targets)
    return targets


def unmet_expected_filenames(vault_dir: Path) -> dict[str, list[str]]:
    """Return a dict mapping category name → list of expected filenames not
    yet present in data_vault/. Enables resume-run scout prompts to target
    specific unmet topics."""
    targets = load_targets(vault_dir)
    data_vault = corpus_dir(vault_dir)
    existing: set[str] = set()
    if data_vault.exists():
        existing = {p.name for p in data_vault.rglob("*.md")}

    out: dict[str, list[str]] = {}
    for cat in targets.categories:
        if cat.is_met or not cat.expected_filenames:
            continue
        missing = [f for f in cat.expected_filenames if f not in existing]
        if missing:
            out[cat.name] = missing
    return out


def existing_vault_filenames(vault_dir: Path) -> list[str]:
    """All note filenames currently in data_vault/ — for scout `exclude_topics`."""
    data_vault = corpus_dir(vault_dir)
    if not data_vault.exists():
        return []
    return sorted({p.name for p in data_vault.rglob("*.md")})


def _hours_since_last_cycle(
    vault_dir: Path, current_cycle: int, now: datetime | None = None
) -> float | None:
    """Read the highest prior cycle's ``cycle-NNN-research.json::timestamp``.

    Returns elapsed hours as a float, or ``None`` if no prior cycle is on
    disk or the timestamp cannot be parsed. Falls back to the scout JSON
    if research.json is absent (e.g. a cycle aborted mid-stream).
    """
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        return None
    latest_ts: datetime | None = None
    for prior in range(current_cycle - 1, 0, -1):
        cycle_3 = f"{prior:03d}"
        for fname in (
            f"cycle-{cycle_3}-research.json",
            f"cycle-{cycle_3}-scout.json",
        ):
            path = cycles_dir / fname
            if not path.is_file():
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            ts = doc.get("timestamp")
            if not isinstance(ts, str):
                continue
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            latest_ts = parsed
            break
        if latest_ts is not None:
            break
    if latest_ts is None:
        return None
    if latest_ts.tzinfo is None:
        latest_ts = latest_ts.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    delta = current - latest_ts
    return max(0.0, delta.total_seconds() / 3600.0)


@dataclass(frozen=True)
class YieldTarget:
    """CG-001 minimum-yield target plus the multipliers that produced it.

    The breakdown is surfaced in the cycle quality report and the
    ``_pipeline/yield-calibration.json`` sidecar (spec 051 FR1) so the gate
    is auditable and the defaults can be re-tuned against real data in 0.7.2.
    """

    target: int
    base: int
    cadence_bucket: str
    cadence_factor: float
    coverage_bucket: str
    coverage_factor: float
    floor: int
    ceiling: int


def _cadence_bucket(hours_since_last_cycle: float | None) -> str:
    """Map time-since-last-cycle to a cadence bucket (spec 051 FR1).

    Boundaries: ``<24h`` daily, ``24h–<168h`` (7d) weekly, ``168h–<336h``
    (14d) biweekly, ``>=336h`` monthly. Cold start (no prior cycle) maps to
    ``monthly`` — the most generous multiplier — because a fresh or long-
    dormant vault should write a full batch (the headline pain the old capped
    model produced: 5–8 notes when 30+ were warranted).
    """
    if hours_since_last_cycle is None:
        return "monthly"
    if hours_since_last_cycle < 24:
        return "daily"
    if hours_since_last_cycle < 168:
        return "weekly"
    if hours_since_last_cycle < 336:
        return "biweekly"
    return "monthly"


def _coverage_bucket(targets: CoverageTargets) -> str:
    """Bucket the overall met/target coverage ratio (spec 051 FR1).

    Boundaries: ``<0.5`` below_50, ``>0.8`` above_80, else 50_to_80 — so
    exactly 50% and 80% land in the middle bucket. No targets → treat as
    fully covered (the gate should not push hard on a vault with nothing to
    cover).
    """
    total_target = sum(max(0, c.target_count) for c in targets.categories)
    if total_target <= 0:
        return "coverage_above_80pct"
    total_met = sum(
        min(max(0, c.met_count), max(0, c.target_count)) for c in targets.categories
    )
    ratio = total_met / total_target
    if ratio < 0.5:
        return "coverage_below_50pct"
    if ratio > 0.8:
        return "coverage_above_80pct"
    return "coverage_50_to_80pct"


def compute_yield_target(
    vault_dir: Path,
    cycle_number: int,
    max_cycles: int,
    cy: CycleYieldSettings | None = None,
) -> YieldTarget:
    """CG-001 minimum-yield target via the spec-051 FR1 multiplicative model.

    ``target = clamp(ceil(base * cadence_factor * coverage_factor),
    min_floor, max_ceiling)``. Deterministic from ``settings.yaml::cycle_yield``
    + vault state — no env vars, no agent choices. When ``cy`` is omitted the
    settings are loaded from ``vault_dir`` (falling back to defaults if
    ``settings.yaml`` is absent/invalid, so bare/test vaults still work).

    ``max_cycles`` is retained for signature compatibility; the new model does
    not divide the backlog across remaining cycles (the old capped formula did).
    """
    if cy is None:
        try:
            cy = load_vault_settings(vault_dir).cycle_yield
        except SettingsError:
            cy = CycleYieldSettings()
    try:
        targets = load_targets(vault_dir)
    except FileNotFoundError:
        targets = CoverageTargets()
    hours = _hours_since_last_cycle(vault_dir, cycle_number)
    cad_bucket = _cadence_bucket(hours)
    cad_factor = cy.cadence_factor.get(cad_bucket, 1.0)
    cov_bucket = _coverage_bucket(targets)
    cov_factor = cy.coverage_factor.get(cov_bucket, 1.0)
    # No remaining coverage work → no mandatory yield (preserves the old
    # model's ``unmet == 0 → 0`` invariant; a fully-covered vault must not be
    # FAILed for writing nothing this cycle). Applies to vaults with all
    # targets met AND to target-less vaults (sum over no categories == 0).
    unmet = sum(max(0, c.target_count - c.met_count) for c in targets.categories)
    if unmet == 0:
        target = 0
    else:
        raw = math.ceil(cy.base_notes_per_cycle * cad_factor * cov_factor)
        target = max(cy.min_floor, min(cy.max_ceiling, raw))
    return YieldTarget(
        target=target,
        base=cy.base_notes_per_cycle,
        cadence_bucket=cad_bucket,
        cadence_factor=cad_factor,
        coverage_bucket=cov_bucket,
        coverage_factor=cov_factor,
        floor=cy.min_floor,
        ceiling=cy.max_ceiling,
    )


def remaining_yield(vault_dir: Path, cycle_number: int, max_cycles: int) -> int:
    """Back-compat shim: the CG-001 target int. See :func:`compute_yield_target`."""
    return compute_yield_target(vault_dir, cycle_number, max_cycles).target
