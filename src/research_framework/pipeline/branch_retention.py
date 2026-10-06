"""Research-branch retention (issue #307, spec 072 FR5's open question).

Spec 072 FR5 keeps a run's ``research/<date>-<time>`` branch after a
constrained landing, deliberately, so a bad landing is one ``git reset``
away. That is correct and is NOT changed here. What the spec's own "Open
questions" section left to a follow-up is the bound: one branch per run,
forever, is real clutter (14 across seven vaults as of 2026-08-30).

**The policy (owner decision D10, 2026-09-08).** Two ceilings, both
configurable in ``settings.yaml``::

    vault_commit:
      retention:
        keep_last: 5        # newest N landed branches are always kept
        max_age_days: 90    # a landed branch older than this is pruned

A landed branch is pruned when it is beyond the newest-``keep_last`` window
OR its tip is older than ``max_age_days`` — each is a ceiling in its own
right, so the count never exceeds N and nothing outlives the age. ``null``
switches a rule off; both ``null`` disables automatic pruning altogether.
The policy is applied automatically when a session starts
(``vault_commit.begin_run``) and after a run lands and the checkout is
back on the base branch (``vault_commit.complete_run``), each reporting
what it pruned in one line; the manual verb
``scripts/prune_research_branches.py <vault> prune`` is kept for the
operator (and for a cron job).

Why the branches are safe to prune at all: after EVERY completed run the
research branch has been merged to the base branch and the checkout has
returned there (spec 072 FR1; ``tests/pipeline/test_vault_commit.py::
TestEveryCompletedRunReturnsToMain``), so an open research branch is only
a record. It never touches an unlanded branch, at any age or count —
dropping unlanded work would defeat the exact recovery guarantee FR5
exists to provide — and never the branch that is currently checked out.

**"Landed" is not commit ancestry.** ``vault_commit._squash_merge`` runs
``git merge --squash <branch>`` followed by a fresh ``git commit`` on
``main`` — that commit is a new object with new parents, so the branch's own
commits are never ancestors of it and ``git merge-base --is-ancestor``
always reports false for a landed branch. Every landing commit's body does
carry a stable, exact marker instead (``vault_commit._format_run_body``):
a line reading ``**Branch:** research/<ts>``. A branch counts as landed iff
``main``'s history contains a commit whose body carries that exact line for
that exact branch name — this is what "verify the branch's content is on
main first" (FR5's own caution) is anchored to.

**One commit carries the marker without carrying the content.** With
``vault_commit.auto_merge: false`` a clean (rc=0) run does NOT merge:
``vault_commit._emit_pointer_commit`` checks ``main`` back out and writes an
EMPTY commit whose body has the same ``**Branch:**`` line, plus the
:data:`POINTER_RETAINED_MARKER` line — the content lives only on the branch,
which is the operator's review gate. The classifier therefore reads each
matching commit's body and counts a branch as landed only when at least one
matching commit is NOT such a pointer. Without that check the review-gate
branch would be a deletion candidate on the very next retention pass.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..vault.frontmatter import split_frontmatter

__all__ = [
    "DEFAULT_KEEP_LAST",
    "DEFAULT_MAX_AGE_DAYS",
    "POINTER_RETAINED_MARKER",
    "ResearchBranch",
    "RetentionPolicy",
    "PruneResult",
    "list_research_branches",
    "is_branch_landed",
    "load_retention_policy",
    "prune_research_branches",
    "apply_retention_policy",
    "format_prune_report",
]

_LOG = logging.getLogger(__name__)

_BRANCH_PREFIX = "research/"

#: D10 defaults: cap the landed records at five per vault, and at ninety days.
DEFAULT_KEEP_LAST = 5
DEFAULT_MAX_AGE_DAYS = 90

#: The line ``vault_commit._emit_pointer_commit`` appends to a pointer commit's
#: body (rc=0 under ``auto_merge: false``). A ``**Branch:**`` marker in a body
#: that also carries this line points AT the branch; it does not land it.
POINTER_RETAINED_MARKER = "*Branch retained per `vault_commit.auto_merge: false`.*"

#: Record separator between commit bodies in one ``git log`` read.
_BODY_SEPARATOR = "\x1e"


def _git(
    vault_dir: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(vault_dir), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _default_base_branch(vault_dir: Path) -> str:
    """Same "main, then master, then init.defaultBranch" fallback

    ``vault_commit._main_branch`` uses — kept as a small local copy rather
    than importing that module's private helper across a module boundary
    (``vault_commit`` imports this module, so the reverse import would be a
    cycle).
    """
    for candidate in ("main", "master"):
        if (
            _git(vault_dir, "rev-parse", "--verify", candidate, check=False).returncode
            == 0
        ):
            return candidate
    result = _git(vault_dir, "config", "--get", "init.defaultBranch", check=False)
    return result.stdout.strip() or "main"


def _current_branch(vault_dir: Path) -> str:
    result = _git(vault_dir, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionPolicy:
    """The two ceilings. ``None`` switches a rule off."""

    keep_last: int | None = DEFAULT_KEEP_LAST
    max_age_days: int | None = DEFAULT_MAX_AGE_DAYS

    @property
    def active(self) -> bool:
        """False when both rules are off — automatic pruning is disabled."""
        return self.keep_last is not None or self.max_age_days is not None


def _read_settings_document(vault_dir: Path) -> dict[str, Any]:
    """The parsed ``settings.yaml``, tolerating the ``---`` wrapper

    ``vault_commit._load_settings`` tolerates. ``{}`` when absent or
    unreadable — retention must never be the reason a session fails to start.
    """
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.exists():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is a hard runtime dep already
        return {}
    try:
        raw = settings_path.read_text(encoding="utf-8")
        split = split_frontmatter(raw)
        body = split[0] if split is not None else raw
        data = yaml.safe_load(body) or {}
    except Exception as exc:
        _LOG.warning(
            "branch_retention: failed to read settings (%s); using defaults", exc
        )
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_rule(value: object, *, key: str, minimum: int, default: int) -> int | None:
    """``None`` → rule off; a well-formed int → that; anything else → default."""
    if value is None:
        return None
    # ``bool`` is an ``int`` subclass; ``keep_last: true`` is a typo, not a 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _LOG.warning(
            "branch_retention: vault_commit.retention.%s must be an integer >= %d "
            "or null, got %r; using the default (%d)",
            key,
            minimum,
            value,
            default,
        )
        return default
    return value


def load_retention_policy(vault_dir: Path) -> RetentionPolicy:
    """Read ``settings.yaml::vault_commit.retention``, defaults applied per key.

    A malformed value warns and falls back to that key's default rather than
    raising — the same fail-towards-safety posture as ``vault_commit``'s own
    settings loader. ``null`` is the explicit way to switch a rule off.
    """
    data = _read_settings_document(vault_dir)
    block = data.get("vault_commit") if isinstance(data, dict) else None
    retention = block.get("retention") if isinstance(block, dict) else None
    if retention is None:
        return RetentionPolicy()
    if not isinstance(retention, dict):
        _LOG.warning(
            "branch_retention: vault_commit.retention must be a mapping, got %r; "
            "using defaults",
            retention,
        )
        return RetentionPolicy()
    keep_last = _coerce_rule(
        retention.get("keep_last", DEFAULT_KEEP_LAST),
        key="keep_last",
        minimum=0,
        default=DEFAULT_KEEP_LAST,
    )
    max_age_days = _coerce_rule(
        retention.get("max_age_days", DEFAULT_MAX_AGE_DAYS),
        key="max_age_days",
        minimum=1,
        default=DEFAULT_MAX_AGE_DAYS,
    )
    return RetentionPolicy(keep_last=keep_last, max_age_days=max_age_days)


# ---------------------------------------------------------------------------
# Listing + classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchBranch:
    """One ``research/*`` branch as it exists right now."""

    name: str
    landed: bool
    tip_committed_at: str  # ISO-8601, the branch tip's own committer date

    def age(self, now: datetime) -> timedelta | None:
        """How old the tip is at *now*; ``None`` when the date cannot be read."""
        try:
            tip = datetime.fromisoformat(self.tip_committed_at)
        except ValueError:
            return None
        if tip.tzinfo is None:
            tip = tip.replace(tzinfo=UTC)
        return now - tip


def is_branch_landed(
    vault_dir: Path, branch: str, *, base_branch: str | None = None
) -> bool:
    """True iff *base_branch*'s history carries a landing commit for *branch*.

    A landing commit is one whose body carries the exact ``**Branch:**``
    marker for *branch* and is NOT an ``auto_merge: false`` pointer (see the
    module docstring). Every matching commit is read, not just the newest:
    a pointer followed by a later real landing of the same branch (an
    operator merging the reviewed branch through the normal path) must
    still count as landed.
    """
    base = base_branch or _default_base_branch(vault_dir)
    marker = f"**Branch:** {branch}"
    result = _git(
        vault_dir,
        "log",
        base,
        "--fixed-strings",
        f"--grep={marker}",
        f"--format={_BODY_SEPARATOR}%B",
        check=False,
    )
    if result.returncode != 0:
        return False
    for body in result.stdout.split(_BODY_SEPARATOR):
        # Whole-line match: `research/<ts>` is a prefix of `research/<ts>-02`,
        # so a substring test lands an unlanded branch on its sibling's commit.
        lines = {line.strip() for line in body.splitlines()}
        if marker in lines and POINTER_RETAINED_MARKER not in body:
            return True
    return False


def list_research_branches(
    vault_dir: Path, *, base_branch: str | None = None
) -> list[ResearchBranch]:
    """Every local ``research/*`` branch, oldest first (branch names sort

    chronologically: ``research/<date>-<time>``), each classified landed or
    not against *base_branch* (default: autodetected main/master).
    """
    base = base_branch or _default_base_branch(vault_dir)
    result = _git(
        vault_dir,
        "for-each-ref",
        "--format=%(refname:short)|%(committerdate:iso-strict)",
        f"refs/heads/{_BRANCH_PREFIX}",
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    branches: list[ResearchBranch] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, tip_committed_at = line.split("|", 1)
        branches.append(
            ResearchBranch(
                name=name,
                landed=is_branch_landed(vault_dir, name, base_branch=base),
                tip_committed_at=tip_committed_at,
            )
        )
    branches.sort(key=lambda b: b.name)
    return branches


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PruneResult:
    """Outcome of a (possibly dry-run) prune pass.

    ``deleted`` is what was (or, under ``dry_run``, would be) removed, and
    ``reasons`` says why per branch — ``"cap"``, ``"age"`` or ``"cap+age"``;
    ``kept_landed`` is landed branches inside both ceilings (plus the
    checked-out branch, which is never a candidate); ``kept_unlanded`` is
    every unlanded branch — always kept, regardless of count or age, never a
    candidate for deletion.
    """

    deleted: list[str]
    kept_landed: list[str]
    kept_unlanded: list[str]
    dry_run: bool
    reasons: dict[str, str] = field(default_factory=dict)


def prune_research_branches(
    vault_dir: Path,
    *,
    keep_last: int | None = DEFAULT_KEEP_LAST,
    max_age_days: int | None = None,
    dry_run: bool = True,
    base_branch: str | None = None,
    now: datetime | None = None,
) -> PruneResult:
    """Delete landed research branches beyond the newest *keep_last* or older

    than *max_age_days* (each ceiling on its own; ``None`` switches one off).

    An unlanded branch is NEVER deleted, no matter how old or how many
    there are — the one hard invariant FR5's caution asks for. Deletion
    uses ``git branch -D`` (a landed branch's content already lives in
    *base_branch*, so this is not a data-loss operation for a branch this
    function classified as landed). The checked-out branch is skipped too:
    git would refuse, and a policy that tries is a policy that logs errors.
    """
    if keep_last is not None and keep_last < 0:
        raise ValueError(f"keep_last must be >= 0 or None, got {keep_last}")
    if max_age_days is not None and max_age_days < 1:
        raise ValueError(f"max_age_days must be >= 1 or None, got {max_age_days}")

    base = base_branch or _default_base_branch(vault_dir)
    branches = list_research_branches(vault_dir, base_branch=base)

    landed = [b for b in branches if b.landed]
    unlanded = [b for b in branches if not b.landed]

    # `branches` (and therefore `landed`) is oldest-first; the newest
    # `keep_last` are the tail of the list.
    beyond_cap: set[str] = set()
    if keep_last is not None:
        beyond_cap = {
            b.name for b in (landed if keep_last == 0 else landed[:-keep_last])
        }

    expired: set[str] = set()
    if max_age_days is not None:
        moment = now or datetime.now(UTC)
        ceiling = timedelta(days=max_age_days)
        for b in landed:
            age = b.age(moment)
            if age is not None and age > ceiling:
                expired.add(b.name)

    current = _current_branch(vault_dir)
    to_delete: list[ResearchBranch] = []
    to_keep: list[ResearchBranch] = []
    reasons: dict[str, str] = {}
    for b in landed:
        why = [
            tag for tag, hit in (("cap", beyond_cap), ("age", expired)) if b.name in hit
        ]
        if why and b.name != current:
            to_delete.append(b)
            reasons[b.name] = "+".join(why)
        else:
            to_keep.append(b)

    if not dry_run:
        refused: list[ResearchBranch] = []
        for b in to_delete:
            proc = _git(vault_dir, "branch", "-D", b.name, check=False)
            if proc.returncode != 0:
                # A linked worktree has it checked out, or its ref is locked.
                # It still exists, so it must not be reported as pruned.
                _LOG.warning(
                    "branch_retention: git would not delete %s: %s",
                    b.name,
                    (proc.stderr or proc.stdout).strip(),
                )
                refused.append(b)
                del reasons[b.name]
        to_delete = [b for b in to_delete if b not in refused]
        to_keep = sorted(to_keep + refused, key=landed.index)

    return PruneResult(
        deleted=[b.name for b in to_delete],
        kept_landed=[b.name for b in to_keep],
        kept_unlanded=[b.name for b in unlanded],
        dry_run=dry_run,
        reasons=reasons,
    )


def apply_retention_policy(
    vault_dir: Path,
    policy: RetentionPolicy | None = None,
    *,
    base_branch: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> PruneResult:
    """Apply *policy* (default: the vault's own settings) — the automatic path.

    An inactive policy (both rules ``null``) returns an empty result without
    touching git at all, so a vault that opted out pays nothing per session.
    """
    if policy is None:
        policy = load_retention_policy(vault_dir)
    if not policy.active:
        return PruneResult(
            deleted=[], kept_landed=[], kept_unlanded=[], dry_run=dry_run
        )
    return prune_research_branches(
        vault_dir,
        keep_last=policy.keep_last,
        max_age_days=policy.max_age_days,
        dry_run=dry_run,
        base_branch=base_branch,
        now=now,
    )


def format_prune_report(result: PruneResult, policy: RetentionPolicy) -> str:
    """The one-line report the automatic paths log and the manual verb prints."""
    verb = "would prune" if result.dry_run else "pruned"
    named = ", ".join(
        f"{name} ({result.reasons.get(name, '?')})" for name in result.deleted
    )
    what = f"{len(result.deleted)} landed research branch(es)"
    if named:
        what += f" — {named}"
    return (
        f"retention: {verb} {what}; keep_last={policy.keep_last}, "
        f"max_age_days={policy.max_age_days}; {len(result.kept_landed)} landed "
        f"kept, {len(result.kept_unlanded)} unlanded kept"
    )
