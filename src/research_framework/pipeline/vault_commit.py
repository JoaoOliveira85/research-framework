"""Auto-commit infrastructure for the mandatory vault git invariant (spec 050).

Every framework operation that mutates a vault MUST go through this module.
See `specs/050-vault-auto-commit/spec.md` for the rationale and lifecycle
diagrams, and Principle X in `.specify/memory/constitution.md` for the
governing rule.

Public surface (only these functions should be called by the rest of the
framework):

    begin_run(vault_dir, *, kind, resume) -> RunContext
        Start a research-style operation. Validates clean main; creates or
        reuses a `research/<timestamp>` branch.

    commit_cycle(vault_dir, *, cycle, summary, ctx) -> CommitResult
        Stage + commit the diff produced by a single research cycle.

    complete_run(vault_dir, *, final_rc, final_reason, ctx) -> CompleteResult
        Squash-merge (rc=0), land + retain branch (rc=1 with commits), drop
        the empty branch (rc=1 with none — issue #250), or rewind
        aborted-cycle tail (rc=2). Push if remote and policy allows.

    Research-branch retention (issue #307, ``branch_retention``) runs inside
    ``begin_run`` (session start) and ``complete_run`` (once the checkout is
    back on the base branch): landed ``research/*`` branches beyond
    ``vault_commit.retention.keep_last`` or older than
    ``vault_commit.retention.max_age_days`` are deleted and reported in one
    INFO line. Unlanded branches are never touched.

    commit_framework_change(vault_dir, *, title, body) -> CommitResult
        Commit an upgrade / scaffold refresh directly on main.

    commit_command_output(vault_dir, *, command, output_paths, summary)
                                                            -> CommitResult
        Commit the side-effect of an ad-hoc CLI verb (ask, write).

Failure model: every public function returns a `CommitResult` /
`CompleteResult` whose `ok` field is False on failure. The only path that
raises is `begin_run` on a dirty main — that surfaces as
`VaultCommitDirtyError` which the CLI is expected to translate into exit 2.
All other failures WARN and let the caller decide.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..vault.frontmatter import split_frontmatter
from . import branch_retention
from .atomic_write import write_json

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is a hard runtime dep already
    yaml = None  # type: ignore[assignment]

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VaultCommitError(Exception):
    """Base error for vault-commit invariant violations."""


class VaultCommitDirtyError(VaultCommitError):
    """Raised by ``begin_run`` when ``main`` has uncommitted changes.

    Translated to exit code 2 by the CLI. The fix is human-mediated:
    the user must commit or stash before re-running the framework.
    """


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CommitResult:
    """Outcome of a single commit attempt."""

    ok: bool
    """True if the commit landed; False otherwise (caller should not crash)."""

    sha: str | None = None
    """Resolved commit SHA when ``ok`` is True."""

    skipped_reason: str | None = None
    """Set to a human-readable reason when ``ok`` is True but nothing was
    actually committed (e.g. ``"no changes"`` or ``"invariant disabled"``)."""

    error: str | None = None
    """Set when ``ok`` is False — short, log-friendly description."""

    untracked_paths: list[str] = field(default_factory=list)
    """Spec 062 FR2: paths still untracked under ``data_vault/`` AFTER the cycle
    commit. Non-empty ⇒ the auto-commit invariant (Principle X) leaked content;
    the orchestrator turns this into a constrained exit."""


@dataclass
class CompleteResult:
    """Outcome of finalising a research run."""

    ok: bool
    merged: bool = False
    branch_retained: bool = False
    pushed: bool = False
    error: str | None = None
    branch: str | None = None


@dataclass(frozen=True)
class _CycleCommit:
    """What the most recent ``commit_cycle`` call did to the branch tip."""

    sha: str
    """The commit that call created (or amended HEAD into)."""

    head_before: str
    """HEAD before it — the parent of a new commit, or the commit an
    ``--amend`` replaced. Resetting here undoes exactly that one call."""

    shas_before: tuple[str, ...]
    """``RunContext.cycle_commit_shas`` before it."""


@dataclass
class RunContext:
    """In-memory state passed across the cycle hooks.

    Also serialised to ``_pipeline/run-commit-state.json`` so a
    ``--resume`` invocation can recover the branch name without
    re-deriving it.
    """

    kind: str
    started_at: str
    branch: str
    base_branch: str
    enabled: bool
    push_policy: str
    cycle_commit_shas: list[str] = field(default_factory=list)
    last_cycle_commit: _CycleCommit | None = field(
        default=None, repr=False, compare=False
    )
    """Set by every ``commit_cycle`` call: the commit it made, or ``None``
    when it committed nothing (no diff, or the commit failed). It is what an
    rc=2 abort is allowed to rewind. In-memory only — never written to the
    state file, so a ``complete_run`` in another process rewinds nothing."""


# ---------------------------------------------------------------------------
# Settings access
# ---------------------------------------------------------------------------


_DEFAULTS = {
    "enabled": True,
    "push_on_complete": "auto",  # auto | never | always
    "auto_merge": True,  # F1 follow-up flag (see spec); honoured here too
}


def _load_settings(vault_dir: Path) -> dict[str, Any]:
    """Return the ``vault_commit:`` block, with defaults applied.

    Reads ``<vault>/settings.yaml``. Any missing key falls back to the
    `_DEFAULTS` table. If the file or parser is unavailable, we treat
    the invariant as enabled with default policy (safest posture —
    "fail towards safety, never towards data loss").
    """
    cfg: dict[str, Any] = dict(_DEFAULTS)
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.exists() or yaml is None:
        return cfg
    try:
        raw = settings_path.read_text(encoding="utf-8")
        # Settings files are plain YAML but our generated examples sometimes
        # wrap them in a YAML frontmatter block (``---\n<body>\n---``). If
        # we see that shape, parse the body; otherwise parse as-is. Both
        # produce the same dict.
        # The closing ``---`` is a whole line: the comment rules
        # (``# -----``) in a file opening with YAML's ``---`` document marker
        # are not one.
        split = split_frontmatter(raw)
        body = split[0] if split is not None else raw
        data = yaml.safe_load(body) or {}
        block = data.get("vault_commit") or {}
        if isinstance(block, dict):
            for k, v in block.items():
                if k in _DEFAULTS:
                    cfg[k] = v
    except Exception as exc:
        _LOG.warning("vault_commit: failed to read settings (%s); using defaults", exc)
    return cfg


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(
    vault_dir: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run ``git -C <vault_dir> <args>`` and return the completed process.

    Centralising lets us add a hermetic env (``GIT_TERMINAL_PROMPT=0``) and
    keeps the rest of the module concise.
    """
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return subprocess.run(
        ["git", "-C", str(vault_dir), *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _is_git_repo(vault_dir: Path) -> bool:
    """True iff *vault_dir* is the top level of a git work tree.

    Being somewhere *inside* one is not enough. Every commit here stages with
    ``git add -A``, which is repository-wide, and a research run branches,
    merges and pushes the whole repository: a vault directory with no
    ``.git`` of its own, sitting in someone else's repo, must not do any of
    that to it. ``--show-prefix`` is empty exactly at the top level.
    """
    try:
        result = _git(
            vault_dir,
            "rev-parse",
            "--is-inside-work-tree",
            "--show-prefix",
            check=False,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    inside, _, prefix = result.stdout.partition("\n")
    return inside.strip() == "true" and prefix.strip() == ""


def _enclosing_repo(vault_dir: Path) -> str | None:
    """Top level of the work tree *vault_dir* sits in, or ``None``."""
    try:
        result = _git(vault_dir, "rev-parse", "--show-toplevel", check=False)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _ensure_repo(vault_dir: Path) -> bool:
    """Return True iff the vault is a git repo and usable.

    No auto-init: a vault that isn't a git repo is a setup problem, and the
    invariant is "commit everything we change," not "secretly start
    versioning a vault the user never asked to version." Log a WARN and
    return False; callers should silently no-op.
    """
    if not _is_git_repo(vault_dir):
        enclosing = _enclosing_repo(vault_dir)
        if enclosing:
            _LOG.warning(
                "vault_commit: %s is not a git repository of its own — it sits "
                "inside the work tree of %s, and committing there would stage "
                "that repository's files; invariant disabled for this run "
                "(`git init` the vault to version it)",
                vault_dir,
                enclosing,
            )
        else:
            _LOG.warning(
                "vault_commit: %s is not a git repository; invariant disabled "
                "for this run",
                vault_dir,
            )
        return False
    return True


def _current_branch(vault_dir: Path) -> str:
    result = _git(vault_dir, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def _main_branch(vault_dir: Path) -> str:
    """Return the conventional default branch name.

    Try ``main`` first, then ``master``, then fall back to whatever
    ``init.defaultBranch`` says. The framework's own scaffold uses
    ``main`` so the common case is the first hit.
    """
    for candidate in ("main", "master"):
        if (
            _git(vault_dir, "rev-parse", "--verify", candidate, check=False).returncode
            == 0
        ):
            return candidate
    result = _git(vault_dir, "config", "--get", "init.defaultBranch", check=False)
    return result.stdout.strip() or "main"


_PORCELAIN_IGNORED_PREFIXES = (
    # Sidecar state changing during the cycle is expected; not a "dirty main"
    # in the sense that matters for the invariant.
    "_pipeline/",
)


def _is_dirty(vault_dir: Path, ignore_pipeline: bool = False) -> bool:
    """Return True if the working tree has uncommitted changes.

    ``ignore_pipeline=True`` masks the ``_pipeline/`` directory because
    sidecars are expected to mutate as soon as we start running things.
    Used by ``begin_run`` to gate a research run.
    """
    result = _git(vault_dir, "status", "--porcelain")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not ignore_pipeline:
        return bool(lines)
    for ln in lines:
        # Porcelain format: "XY <path>" where X+Y are status flags.
        path = ln[3:] if len(ln) > 3 else ln
        path = path.strip().strip('"')
        if path.startswith(_PORCELAIN_IGNORED_PREFIXES):
            continue
        return True
    return False


def is_working_tree_dirty(vault: Path) -> bool:
    """Public wrapper over :func:`_is_dirty` for non-research pre-flight guards.

    A vault that is not a git repository of its own has no working tree to be
    dirty, and every commit hook in this module skips it. ``git status`` fails
    there, and ``./vault update`` — the caller — reads any failure of this
    check as "dirty": it told the operator of an unversioned vault to "commit
    or stash". Spec 027 wants such vaults to degrade gracefully, so the answer
    is ``False``, with the same WARNING the commit hooks log.
    """
    if not _ensure_repo(vault):
        return False
    return _is_dirty(vault)


def _has_remote(vault_dir: Path) -> bool:
    result = _git(vault_dir, "remote", check=False)
    return bool(result.stdout.strip())


_BRANCH_TS_FMT = "%Y-%m-%d-%H%M"


def _branch_name_taken(vault_dir: Path, name: str) -> bool:
    """True when *name* exists as a ref OR was ever landed on the base branch.

    The second half is issue #307's hazard: retention deletes a landed
    branch, which frees its name, and the landing commit's ``**Branch:**``
    marker stays on main forever. A new run that re-used the name would be
    classified "landed" by that stale marker while still in progress — and a
    stranded copy of it (Ctrl-C, checkout main) would be pruned as a record
    when it is unlanded work. A name is therefore never reused in a vault.
    """
    if _git(vault_dir, "rev-parse", "--verify", name, check=False).returncode == 0:
        return True
    return branch_retention.is_branch_landed(vault_dir, name)


def _new_research_branch_name(vault_dir: Path, now: datetime | None = None) -> str:
    """Return ``research/<timestamp>``, dedup-suffixed if it was ever used.

    Edge case: re-running ``./vault research`` twice in the same minute on
    the same vault would otherwise produce a collision. We append
    ``-NN`` (2..n) to disambiguate — against live refs and against names a
    pruned branch once carried (see :func:`_branch_name_taken`).
    """
    now = now or datetime.now()
    base = f"research/{now.strftime(_BRANCH_TS_FMT)}"
    if not _branch_name_taken(vault_dir, base):
        return base
    for suffix in range(2, 100):
        candidate = f"{base}-{suffix:02d}"
        if not _branch_name_taken(vault_dir, candidate):
            return candidate
    raise VaultCommitError(
        "vault_commit: could not allocate a unique research branch name; "
        f"too many collisions under {base}-NN"
    )


# ---------------------------------------------------------------------------
# Sidecar state (run-commit-state.json)
# ---------------------------------------------------------------------------
#
# The state file lives under ``.git/`` rather than ``_pipeline/`` because it
# is *control* metadata for the auto-commit invariant, not part of the
# vault's content. Putting it in the tracked tree would (a) make every
# per-cycle commit_cycle call dirty the working tree again immediately
# after committing, and (b) bleed branch-lifecycle bookkeeping into the
# vault's history. ``.git/`` is the natural home: never tracked, scoped to
# the repo, survives across CLI invocations on the same checkout.


_STATE_FILE = ".git/research-framework/vault-commit-state.json"
_STATE_GIT_PATH = _STATE_FILE.removeprefix(".git/")


def _state_path(vault_dir: Path) -> Path:
    """Where this checkout's run state lives, as git resolves it.

    <vault>/.git/research-framework/… in an ordinary clone — but .git
    is a *file* when the vault is a linked worktree (or a submodule), and
    the per-checkout git dir is elsewhere. rev-parse --git-path answers
    for all three, and gives a linked worktree its own state rather than
    one shared with the checkout it was added from.
    """
    try:
        result = _git(
            vault_dir, "rev-parse", "--git-path", _STATE_GIT_PATH, check=False
        )
    except FileNotFoundError:
        return vault_dir / _STATE_FILE
    resolved = result.stdout.strip()
    if result.returncode != 0 or not resolved:
        return vault_dir / _STATE_FILE
    # Relative answers are relative to the directory git ran in.
    return vault_dir / resolved


_TRANSIENT_STATE_FIELDS = ("last_cycle_commit",)


def _write_state(vault_dir: Path, ctx: RunContext) -> None:
    path = _state_path(vault_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(ctx)
    for name in _TRANSIENT_STATE_FIELDS:
        data.pop(name, None)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_state(vault_dir: Path) -> RunContext | None:
    path = _state_path(vault_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RunContext(**data)
    except Exception:
        return None


def _clear_state(vault_dir: Path) -> None:
    path = _state_path(vault_dir)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Commit message rendering
# ---------------------------------------------------------------------------


_PREFIX_BY_KIND = {
    "research-cycle": "research: ",
    "research-run": "research run: ",
    "framework": "framework: ",
    "vault-output": "vault: ",
    "vault-sync": "vault sync: ",
}


def _render_message(kind: str, title_tail: str, body: str) -> str:
    prefix = _PREFIX_BY_KIND.get(kind, "vault: ")
    title = f"{prefix}{title_tail}".strip()
    # Conventional commit shape: title, blank line, body.
    return f"{title}\n\n{body}".rstrip() + "\n"


def _format_cycle_body(summary: dict[str, Any]) -> str:
    """Render the body of a per-cycle commit message.

    ``summary`` is a free-form dict; we recognise common keys but
    gracefully render whatever we get. This keeps the orchestrator
    integration thin — callers can pass partial summaries and the
    output is still readable.
    """
    notes_added = summary.get("notes_added")
    notes_updated = summary.get("notes_updated")
    notes_archived = summary.get("notes_archived")
    coverage = summary.get("coverage")  # list[(category, "X/Y (+delta)")]
    wall_time = summary.get("wall_time_human")
    gate_verdict = summary.get("gate_verdict")
    tokens_in = summary.get("tokens_in")
    tokens_out = summary.get("tokens_out")
    cost_usd = summary.get("cost_usd")
    exit_reason = summary.get("exit_reason")

    lines: list[str] = []

    lines.append("**Changed**")
    if notes_added is not None:
        lines.append(f"- {notes_added} note(s) added")
    if notes_updated is not None:
        lines.append(f"- {notes_updated} note(s) updated")
    if notes_archived is not None:
        lines.append(f"- {notes_archived} note(s) archived")
    if len(lines) == 1:
        lines.append("- (no per-note breakdown captured)")

    if coverage:
        lines.append("")
        lines.append("**Coverage**")
        for entry in coverage:
            if isinstance(entry, dict):
                cat = entry.get("category", "?")
                line = entry.get("line", "")
                lines.append(f"- {cat}: {line}")
            else:
                lines.append(f"- {entry}")

    health_bits: list[str] = []
    if wall_time is not None:
        health_bits.append(f"wall time: {wall_time}")
    if gate_verdict is not None:
        health_bits.append(f"gate verdict: {gate_verdict}")
    if tokens_in is not None or tokens_out is not None:
        tin = tokens_in if tokens_in is not None else "?"
        tout = tokens_out if tokens_out is not None else "?"
        health_bits.append(f"agent tokens: {tin} in / {tout} out")
    if cost_usd is not None:
        try:
            health_bits.append(f"${float(cost_usd):.4f} spent")
        except (TypeError, ValueError):
            health_bits.append(f"{cost_usd} spent")
    if exit_reason:
        health_bits.append(f"exit: {exit_reason}")

    if health_bits:
        lines.append("")
        lines.append("**Cycle health**")
        for bit in health_bits:
            lines.append(f"- {bit}")

    return "\n".join(lines)


def _format_run_body(ctx: RunContext, final_rc: int, final_reason: str) -> str:
    n = len(ctx.cycle_commit_shas)
    rc_text = {0: "complete", 1: "constrained", 2: "aborted"}.get(
        final_rc, f"rc={final_rc}"
    )
    lines = [
        f"**Outcome:** {rc_text} ({final_reason or 'no further detail'})",
        "",
        f"**Cycles squashed:** {n}",
        f"**Branch:** {ctx.branch}",
        f"**Started:** {ctx.started_at}",
        f"**Completed:** {datetime.now(UTC).isoformat()}",
    ]
    return "\n".join(lines)


def _apply_retention(vault_dir: Path, base_branch: str, *, stage: str) -> None:
    """Issue #307: prune landed research branches per the vault's policy.

    Best-effort by construction — retention is housekeeping over records
    whose content is already on *base_branch*, and it must never be the
    reason a session fails to start or a landing fails to finish. Anything
    unexpected WARNs and the caller carries on. One INFO line reports what
    was pruned; silence means nothing was.
    """
    try:
        policy = branch_retention.load_retention_policy(vault_dir)
        result = branch_retention.apply_retention_policy(
            vault_dir, policy, base_branch=base_branch
        )
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning(
            "vault_commit: research-branch retention skipped at %s: %s", stage, exc
        )
        return
    if result.deleted:
        _LOG.info(
            "vault_commit: %s [%s]",
            branch_retention.format_prune_report(result, policy),
            stage,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def begin_run(
    vault_dir: Path,
    *,
    kind: str = "research",
    resume: bool = False,
    now: datetime | None = None,
) -> RunContext | None:
    """Open a research-style operation on a clean ``main``.

    Returns ``None`` if the invariant is disabled or the directory isn't a
    git repo (caller treats this as "best-effort skipped"). Raises
    :class:`VaultCommitDirtyError` if ``main`` has uncommitted changes —
    that is a HARD STOP per Principle X.
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        _LOG.info("vault_commit: invariant disabled in settings; skipping")
        return None
    if not _ensure_repo(vault_dir):
        return None

    base_branch = _main_branch(vault_dir)
    current = _current_branch(vault_dir)

    # Resume case: already on a research branch → reuse it (and its
    # cycle-commit history if we have state on disk).
    if current.startswith("research/"):
        if resume:
            _LOG.info(
                "vault_commit: resuming on existing branch %s (from %s)",
                current,
                base_branch,
            )
            # Issue #307: a session start, even a resumed one. The branch
            # being resumed is unlanded by definition and is HEAD besides,
            # so it is never a candidate; only older landed records are.
            _apply_retention(vault_dir, base_branch, stage="session start")
            existing = _read_state(vault_dir)
            if existing and existing.branch == current:
                return existing
            ctx = RunContext(
                kind=kind,
                started_at=datetime.now(UTC).isoformat(),
                branch=current,
                base_branch=base_branch,
                enabled=True,
                push_policy=cfg["push_on_complete"],
                # No state for this branch (an rc=2 abort clears it): the
                # branch itself is the record of what the run committed.
                cycle_commit_shas=_cycle_commits_on_branch(vault_dir, base_branch),
            )
            _write_state(vault_dir, ctx)
            return ctx
        # Fresh run while a stale branch is checked out → refuse rather
        # than silently mixing histories.
        raise VaultCommitDirtyError(
            f"vault_commit: vault is on research branch '{current}' but "
            "this is not a --resume run. Either pass --resume to continue "
            "that branch, or merge/drop it and switch back to "
            f"'{base_branch}' before running again."
        )

    # Fresh run: must be on main (or master) and clean (ignoring _pipeline).
    if current != base_branch:
        raise VaultCommitDirtyError(
            f"vault_commit: expected to start from '{base_branch}' but "
            f"current branch is '{current}'. Switch back or pass --resume."
        )
    if _is_dirty(vault_dir, ignore_pipeline=True):
        raise VaultCommitDirtyError(
            f"vault_commit: '{base_branch}' has uncommitted changes. "
            "Commit or stash them before running the framework — the "
            "auto-commit invariant must not co-mingle your manual edits "
            "with framework-generated content. See Principle X."
        )

    # Issue #307 / D10: retention is checked when a vault session starts —
    # after the dirty-main hard stop, so a refused session has no side
    # effects, and before the new branch exists, so it is never in the count.
    _apply_retention(vault_dir, base_branch, stage="session start")

    branch = _new_research_branch_name(vault_dir, now=now)
    _git(vault_dir, "checkout", "-b", branch)
    ctx = RunContext(
        kind=kind,
        started_at=datetime.now(UTC).isoformat(),
        branch=branch,
        base_branch=base_branch,
        enabled=True,
        push_policy=cfg["push_on_complete"],
    )
    _write_state(vault_dir, ctx)
    _LOG.info(
        "vault_commit: opened run branch %s (base %s, push policy %s)",
        branch,
        base_branch,
        ctx.push_policy,
    )
    return ctx


_CYCLE_SUBJECT_RE = re.compile(r"^research: cycle (\d+)\b")


def _head_cycle_number(vault_dir: Path) -> int | None:
    """Return the cycle number of the HEAD commit if it is a ``research: cycle N``
    commit, else ``None``. Used for spec-062 FR2 per-cycle commit idempotency."""
    res = _git(vault_dir, "log", "-1", "--format=%s", check=False)
    if res.returncode != 0:
        return None
    m = _CYCLE_SUBJECT_RE.match(res.stdout.strip())
    return int(m.group(1)) if m else None


def _cycle_commits_on_branch(vault_dir: Path, base_branch: str) -> list[str]:
    """SHAs of the ``research: cycle N`` commits HEAD carries that
    *base_branch* does not, oldest first — ``RunContext.cycle_commit_shas``
    as git records it, for a resume that finds no state file."""
    res = _git(
        vault_dir,
        "log",
        "--reverse",
        "--format=%H %s",
        f"{base_branch}..HEAD",
        check=False,
    )
    if res.returncode != 0:
        return []
    shas: list[str] = []
    for line in res.stdout.splitlines():
        sha, _, subject = line.partition(" ")
        if _CYCLE_SUBJECT_RE.match(subject):
            shas.append(sha)
    return shas


def _run_committed_nothing(vault_dir: Path, ctx: RunContext) -> bool:
    """True only when the run's branch carries no commit its base lacks.

    This is what makes dropping the branch safe, so it is asked of git and
    not only of ``ctx.cycle_commit_shas``. That list is bookkeeping: it does
    not count a commit the operator made on the branch, and it is only as
    good as the state that survived to this process. When git cannot answer
    (a missing ref), the branch is not provably empty and is kept.
    """
    if ctx.cycle_commit_shas:
        return False
    res = _git(
        vault_dir,
        "rev-list",
        "--count",
        f"{ctx.base_branch}..{ctx.branch}",
        check=False,
    )
    return res.returncode == 0 and res.stdout.strip() == "0"


def _untracked_under(vault_dir: Path, subdir: str) -> list[str]:
    """Return paths still untracked under ``subdir`` (porcelain ``??`` entries).

    Spec 062 FR2: ``_stage_and_commit`` does ``git add -A`` then commits, so a
    non-empty result here means content appeared (or is gitignored) under
    ``data_vault/`` AFTER the cycle commit — a Principle-X leak.
    """
    res = _git(
        vault_dir,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        subdir,
        check=False,
    )
    if res.returncode != 0:
        return []
    out: list[str] = []
    for ln in res.stdout.splitlines():
        if not ln.strip() or not ln.startswith("??"):
            continue
        path = ln[3:].strip().strip('"') if len(ln) > 3 else ln.strip()
        out.append(path)
    return out


def commit_cycle(
    vault_dir: Path,
    *,
    cycle: int,
    summary: dict[str, Any] | None = None,
    ctx: RunContext | None = None,
) -> CommitResult:
    """Stage everything in the working tree and commit it as cycle ``N``.

    Best-effort: on any git failure we log + write a sidecar and return
    a ``CommitResult(ok=False, ...)`` so the cycle's own rc is preserved.

    Spec 062 FR2: per-cycle commit is **idempotent** — a same-cycle re-emit
    (e.g. a metadata correction) folds into the single ``research: cycle N``
    commit via ``--amend`` instead of producing a second one; and a post-commit
    sweep flags any content left untracked under ``data_vault/`` (a Principle-X
    leak) on the returned ``CommitResult.untracked_paths``.
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        return CommitResult(ok=True, skipped_reason="invariant disabled")
    if not _ensure_repo(vault_dir):
        return CommitResult(ok=True, skipped_reason="not a git repo")

    summary = summary or {}
    short_summary = summary.get("short", "") or summary.get("exit_reason", "")
    short_summary = (short_summary or f"cycle {cycle}").strip()
    title_tail = (
        f"cycle {cycle} — {short_summary}" if short_summary else f"cycle {cycle}"
    )
    body = _format_cycle_body(summary)
    message = _render_message("research-cycle", title_tail, body)

    # FR2: if HEAD is already this cycle's commit, fold the re-emit into it.
    amend = _head_cycle_number(vault_dir) == cycle

    def _record(sha: str) -> None:
        if ctx is None:
            return
        if amend and ctx.cycle_commit_shas:
            ctx.cycle_commit_shas[-1] = sha
        else:
            ctx.cycle_commit_shas.append(sha)

    head_before = _git(vault_dir, "rev-parse", "HEAD", check=False)
    shas_before = tuple(ctx.cycle_commit_shas) if ctx is not None else ()

    result = _stage_and_commit(
        vault_dir,
        message=message,
        on_success_record=_record,
        ctx=ctx,
        sidecar_label=f"cycle-{cycle:03d}",
        amend=amend,
    )

    if ctx is not None:
        # What an abort may undo: this call's commit, and only if it made one.
        # A skipped ("no changes") or failed commit leaves the tip as it was —
        # an earlier cycle's work, which is not this cycle's to rewind.
        ctx.last_cycle_commit = (
            _CycleCommit(
                sha=result.sha,
                head_before=head_before.stdout.strip(),
                shas_before=shas_before,
            )
            if result.ok and result.sha and head_before.returncode == 0
            else None
        )

    # FR2: nothing under data_vault/ may remain untracked after the commit.
    untracked = _untracked_under(vault_dir, "data_vault")
    if untracked:
        result.untracked_paths = untracked
        _LOG.warning(
            "vault_commit: %d untracked path(s) under data_vault/ after cycle %d "
            "commit (Principle X leak): %s",
            len(untracked),
            cycle,
            ", ".join(untracked[:5]),
        )
    return result


def complete_run(
    vault_dir: Path,
    *,
    final_rc: int,
    final_reason: str = "",
    ctx: RunContext | None = None,
) -> CompleteResult:
    """Finalise a research run started by :func:`begin_run`.

    See spec 050 §"Lifecycle: research run" for the rc-by-rc behaviour.
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        return CompleteResult(ok=True)
    if not _ensure_repo(vault_dir):
        return CompleteResult(ok=True)

    if ctx is None:
        ctx = _read_state(vault_dir)
    if ctx is None:
        # Nothing to finalise. This can legitimately happen if begin_run
        # was skipped (disabled, no repo, etc.); not an error.
        return CompleteResult(ok=True)

    auto_merge = cfg["auto_merge"]
    push_policy = cfg["push_on_complete"]
    branch_deleted = False

    if final_rc == 0 and auto_merge:
        result = _squash_merge(vault_dir, ctx, final_reason)
    elif final_rc == 0 and not auto_merge:
        # F1 follow-up path: leave the per-cycle commits on the branch
        # and emit a pointer commit on main.
        result = _emit_pointer_commit(vault_dir, ctx, final_reason)
    elif final_rc == 2:
        # Aborted: rewind a stub cycle-commit if one exists.
        result = _rewind_aborted_tail(vault_dir, ctx)
    elif final_rc == 1 and _run_committed_nothing(vault_dir, ctx):
        # Issue #250 / spec 072 FR1: a constrained exit (budget cap,
        # max_cycles, source-exhausted — see spec 070 F5, which reaches
        # this exact path on a resume anchored past `--max-cycles`) that
        # committed NOTHING has nothing to land and nothing to review.
        # Unlike the "nothing landable" `else` branch below, this isn't a
        # case for holding the branch for a human to look at — there is no
        # per-cycle history on it. Check main back out and drop it, rather
        # than stranding one more empty `research/<ts>` branch per
        # invocation. Independent of `auto_merge`: that flag governs
        # whether to auto-land *content*, and there is none here either
        # way.
        result = _delete_empty_branch(vault_dir, ctx)
        branch_deleted = True
    elif final_rc == 1 and auto_merge:
        # Spec 072: a constrained exit is a DESIGNED terminal state — budget
        # cap, max_cycles, source-exhausted — not a failure. Its content is as
        # valid as a clean finish, so land it and leave the operator on the base
        # branch rather than handing them a "should I merge this?" question the
        # framework can answer. The branch is retained (FR5): unlike rc=0 the
        # run left work undone, so its per-cycle history is worth keeping.
        #
        # A run that committed nothing has nothing to land; the arm above
        # dropped its branch. rc=2 never reaches here — it rewinds instead,
        # and a run that died mid-cycle is exactly what a human should review.
        result = _squash_merge(
            vault_dir, ctx, final_reason, final_rc=final_rc, delete_branch=False
        )
    else:
        # Nothing landable: leave branch + commits in place.
        result = CompleteResult(
            ok=True,
            branch_retained=True,
            branch=ctx.branch,
        )
        _LOG.info(
            "vault_commit: run ended rc=%d (%s); branch %s retained for review",
            final_rc,
            final_reason or "no reason",
            ctx.branch,
        )

    # Issue #307 / D10: once a run has landed and the checkout is back on the
    # base branch, every open research/* branch is only a record — apply the
    # retention ceilings now rather than leaving the count to grow until the
    # next session start. The paths that deliberately stay on the research
    # branch (rc=2 abort, a constrained rc=1 under `auto_merge: false`) are
    # skipped by the checkout test, not by enumerating them. A clean rc=0
    # under `auto_merge: false` DOES return to main (pointer commit, content
    # only on the branch) — that branch is unlanded to the classifier
    # (`branch_retention.POINTER_RETAINED_MARKER`) and never a candidate.
    if result.ok and _current_branch(vault_dir) == ctx.base_branch:
        _apply_retention(vault_dir, ctx.base_branch, stage="run complete")

    # Push attempt (best-effort). The empty-branch path already checked
    # `ctx.base_branch` back out and deleted `ctx.branch` — pushing a branch
    # name that no longer exists would just fail, so it targets base too.
    if _should_push(vault_dir, push_policy):
        target = (
            ctx.base_branch
            if ((final_rc == 0 and auto_merge) or branch_deleted)
            else ctx.branch
        )
        pushed_ok, push_err = _push(vault_dir, target)
        result.pushed = pushed_ok
        if not pushed_ok:
            _LOG.warning("vault_commit: push of %s failed: %s", target, push_err)

    if result.ok and final_rc == 0 and auto_merge:
        _clear_state(vault_dir)
    elif result.ok and branch_deleted:
        # Same reasoning as the rc=0 clean-merge case: the branch this state
        # pointed at is gone, so there is nothing left for a `--resume` to
        # recover.
        _clear_state(vault_dir)
    elif result.ok and final_rc == 2:
        _clear_state(vault_dir)

    return result


def commit_framework_change(
    vault_dir: Path,
    *,
    title: str,
    body: str = "",
) -> CommitResult:
    """Commit a framework upgrade / scaffold refresh directly on the base branch.

    Called twice around destructive upgrades: once to capture the
    pre-upgrade state (idempotent if clean), once after. Both calls are
    safe to invoke even when there are no changes (silent no-op).
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        return CommitResult(ok=True, skipped_reason="invariant disabled")
    if not _ensure_repo(vault_dir):
        return CommitResult(ok=True, skipped_reason="not a git repo")
    message = _render_message("framework", title, body)
    return _stage_and_commit(
        vault_dir,
        message=message,
        sidecar_label="framework",
    )


def commit_regrade(
    vault_dir: Path,
    *,
    count: int,
    body: str = "",
    date: str | None = None,
) -> CommitResult:
    """Commit a ``./vault re-grade`` reinstatement batch (spec 066 FR4/Q9).

    One commit ``regrade(<YYYY-MM-DD>): N notes reinstated`` per run; never an
    empty commit (the caller only invokes this when ``count >= 1``). Failure
    WARNs but the on-disk moves persist (idempotent next run).
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        return CommitResult(ok=True, skipped_reason="invariant disabled")
    if not _ensure_repo(vault_dir):
        return CommitResult(ok=True, skipped_reason="not a git repo")
    when = date or datetime.now(UTC).strftime("%Y-%m-%d")
    title = f"regrade({when}): {count} note{'s' if count != 1 else ''} reinstated"
    message = f"{title}\n\n{body}".rstrip() + "\n"
    return _stage_and_commit(vault_dir, message=message, sidecar_label="regrade")


def commit_command_output(
    vault_dir: Path,
    *,
    command: str,
    output_paths: list[Path] | None = None,
    summary: str = "",
) -> CommitResult:
    """Commit the side-effect of an ad-hoc CLI verb (``ask``, ``write``, ...).

    ``output_paths`` is advisory — we ``git add -A`` regardless to catch
    sidecar writes the verb produced. If nothing changed, we record a
    skip rather than producing an empty commit.
    """
    cfg = _load_settings(vault_dir)
    if not cfg["enabled"]:
        return CommitResult(ok=True, skipped_reason="invariant disabled")
    if not _ensure_repo(vault_dir):
        return CommitResult(ok=True, skipped_reason="not a git repo")

    paths_line = ""
    if output_paths:
        rels = []
        for p in output_paths:
            try:
                rels.append(str(Path(p).resolve().relative_to(vault_dir.resolve())))
            except (ValueError, OSError):
                rels.append(str(p))
        paths_line = "**Outputs**\n" + "\n".join(f"- {r}" for r in rels)

    body_bits = []
    if summary:
        body_bits.append(summary)
    if paths_line:
        if body_bits:
            body_bits.append("")
        body_bits.append(paths_line)
    body = "\n".join(body_bits)
    title_tail = summary.splitlines()[0] if summary else command
    message = _render_message("vault-output", f"{command} — {title_tail}", body)
    return _stage_and_commit(
        vault_dir,
        message=message,
        sidecar_label=f"vault-{command}",
    )


# ---------------------------------------------------------------------------
# Internal mechanics
# ---------------------------------------------------------------------------


def _stage_and_commit(
    vault_dir: Path,
    *,
    message: str,
    on_success_record: Any = None,
    ctx: RunContext | None = None,
    sidecar_label: str = "vault",
    amend: bool = False,
) -> CommitResult:
    """Shared "git add -A + git commit" helper used by every public hook.

    Why ``git add -A``? The framework writes to many directories
    (``data_vault/``, ``_pipeline/``, ``modules/``); a commit hook that
    wants to be conservative would still miss new directories. We trust
    ``.gitignore`` (already populated by the scaffold) to keep noise out.

    ``amend`` (spec 062 FR2): fold the staged changes into the existing HEAD
    commit (re-using ``message``) instead of creating a new one — the per-cycle
    commit idempotency path.
    """
    try:
        _git(vault_dir, "add", "-A")
    except subprocess.CalledProcessError as exc:
        err = _short_err(exc)
        _emit_sidecar(vault_dir, sidecar_label, stage="stage", error=err)
        return CommitResult(ok=False, error=f"git add failed: {err}")

    # Detect empty diff *after* staging so this is reliable.
    status = _git(vault_dir, "diff", "--cached", "--quiet", check=False)
    if status.returncode == 0:
        if message.startswith("framework: snapshot before update"):
            try:
                _git(vault_dir, "commit", "--allow-empty", "-m", message)
            except subprocess.CalledProcessError as exc:
                err = _short_err(exc)
                _emit_sidecar(vault_dir, sidecar_label, stage="commit", error=err)
                return CommitResult(ok=False, error=f"git commit failed: {err}")
            sha_result = _git(vault_dir, "rev-parse", "HEAD")
            sha = sha_result.stdout.strip()
            if on_success_record is not None:
                try:
                    on_success_record(sha)
                except Exception:  # pragma: no cover - defensive
                    pass
            if ctx is not None:
                _write_state(vault_dir, ctx)
            return CommitResult(ok=True, sha=sha)
        # A byte-identical re-emit (no staged diff) is a content no-op: the
        # canonical file already holds this content (spec 062 FR2 Q2). No
        # second commit, no ` N.md` fork.
        return CommitResult(ok=True, skipped_reason="no changes")

    commit_args = ["commit", "-m", message]
    if amend:
        commit_args.insert(1, "--amend")
    try:
        _git(vault_dir, *commit_args)
    except subprocess.CalledProcessError as exc:
        err = _short_err(exc)
        _emit_sidecar(vault_dir, sidecar_label, stage="commit", error=err)
        return CommitResult(ok=False, error=f"git commit failed: {err}")

    sha_result = _git(vault_dir, "rev-parse", "HEAD")
    sha = sha_result.stdout.strip()
    if on_success_record is not None:
        try:
            on_success_record(sha)
        except Exception:  # pragma: no cover - defensive
            pass
    if ctx is not None:
        _write_state(vault_dir, ctx)
    return CommitResult(ok=True, sha=sha)


def _squash_merge(
    vault_dir: Path,
    ctx: RunContext,
    reason: str,
    *,
    final_rc: int = 0,
    delete_branch: bool = True,
) -> CompleteResult:
    """Squash ``ctx.branch`` into ``ctx.base_branch``; optionally keep the branch.

    ``delete_branch=False`` is the spec-072 constrained-exit path: the run is
    over and its content lands, but the per-cycle history stays on the branch so
    a bad landing is recoverable (FR5).
    """
    on_base = False
    try:
        _git(vault_dir, "checkout", ctx.base_branch)
        on_base = True
        # ``--squash`` stages the merge as if it were a single change but
        # does not commit; we then commit with the run-level message.
        _git(vault_dir, "merge", "--squash", ctx.branch)
    except subprocess.CalledProcessError as exc:
        err = _short_err(exc)
        _LOG.warning("vault_commit: squash-merge failed: %s", err)
        if on_base:
            _back_out_of_failed_landing(vault_dir, ctx)
        return CompleteResult(
            ok=False,
            branch_retained=True,
            error=err,
            branch=ctx.branch,
        )
    title_tail = (
        f"{ctx.branch.removeprefix('research/')} — {len(ctx.cycle_commit_shas)} "
        f"cycle(s)"
    )
    body = _format_run_body(ctx, final_rc=final_rc, final_reason=reason)
    message = _render_message("research-run", title_tail, body)
    try:
        _git(vault_dir, "commit", "-m", message)
    except subprocess.CalledProcessError as exc:
        # Edge case: branch contained nothing committable (all cycles
        # skipped). Treat as silent merge-with-no-changes — leave main
        # untouched and report it.
        if "nothing to commit" in (exc.stdout or "") + (exc.stderr or ""):
            _LOG.info("vault_commit: squash-merge produced no diff; main unchanged")
        else:
            err = _short_err(exc)
            _LOG.warning("vault_commit: run-commit failed: %s", err)
            return CompleteResult(
                ok=False,
                branch_retained=True,
                error=err,
                branch=ctx.branch,
            )
    if not delete_branch:
        _LOG.info(
            "vault_commit: landed %s on %s (rc=%d, %s); branch retained",
            ctx.branch,
            ctx.base_branch,
            final_rc,
            reason,
        )
        return CompleteResult(ok=True, branch_retained=True, branch=ctx.branch)

    # Delete the branch only after a successful commit + checkout.
    try:
        _git(vault_dir, "branch", "-D", ctx.branch)
    except subprocess.CalledProcessError as exc:
        _LOG.warning(
            "vault_commit: failed to delete branch %s: %s",
            ctx.branch,
            _short_err(exc),
        )
    return CompleteResult(ok=True, merged=True, branch=ctx.branch)


def _back_out_of_failed_landing(vault_dir: Path, ctx: RunContext) -> None:
    """Undo a squash-merge that stopped partway and return to the run branch.

    Spec 072 FR3: a landing that cannot apply must "stop, stay on the branch,
    and say so". A conflicted ``merge --squash`` leaves the base branch checked
    out with unmerged index entries and conflict markers in the notes, and the
    next ``git add -A`` — any ``./vault`` verb's auto-commit — commits those
    markers to the base branch.

    ``reset --merge`` runs only when the merge left unmerged paths. Git starts
    a real merge only from an index that matches HEAD, so in that case the
    index holds nothing but the merge and resetting it loses nothing: every
    change is still on ``ctx.branch``, and unstaged edits are kept. When the
    merge refused to start instead (the operator has staged work), the index
    is the operator's and is left alone; checking the branch back out carries
    it along.
    """
    unmerged = _git(vault_dir, "ls-files", "--unmerged", check=False).stdout.strip()
    try:
        if unmerged:
            _git(vault_dir, "reset", "--merge")
        _git(vault_dir, "checkout", ctx.branch)
    except subprocess.CalledProcessError as exc:
        _LOG.warning(
            "vault_commit: could not return to %s after the failed landing (%s); "
            "%s is checked out — run `git status` there before anything else",
            ctx.branch,
            _short_err(exc),
            ctx.base_branch,
        )
        return
    _LOG.warning(
        "vault_commit: %s was NOT landed on %s (%s). %s is untouched and the "
        "run's commits are on %s, which is checked out; merge it by hand.",
        ctx.branch,
        ctx.base_branch,
        "the two do not merge cleanly" if unmerged else "the merge did not start",
        ctx.base_branch,
        ctx.branch,
    )


def _emit_pointer_commit(
    vault_dir: Path, ctx: RunContext, reason: str
) -> CompleteResult:
    """F1 follow-up path: leave branch in place, drop a pointer on main."""
    branch_sha_result = _git(vault_dir, "rev-parse", ctx.branch)
    branch_sha = branch_sha_result.stdout.strip()
    try:
        _git(vault_dir, "checkout", ctx.base_branch)
    except subprocess.CalledProcessError as exc:
        return CompleteResult(
            ok=False,
            branch_retained=True,
            error=_short_err(exc),
            branch=ctx.branch,
        )
    title_tail = (
        f"{ctx.branch.removeprefix('research/')} — see branch @ {branch_sha[:8]}"
    )
    body = _format_run_body(ctx, final_rc=0, final_reason=reason)
    # The same `**Branch:**` line a real landing writes is in this body, but
    # nothing landed: retention's classifier keys off this trailer to tell
    # the two apart, so it is the shared constant, not a local string.
    body += f"\n\n{branch_retention.POINTER_RETAINED_MARKER}"
    message = _render_message("research-run", title_tail, body)
    # Empty commit because main has no diff vs the start of the run.
    try:
        _git(vault_dir, "commit", "--allow-empty", "-m", message)
    except subprocess.CalledProcessError as exc:
        return CompleteResult(
            ok=False,
            branch_retained=True,
            error=_short_err(exc),
            branch=ctx.branch,
        )
    return CompleteResult(
        ok=True, merged=False, branch_retained=True, branch=ctx.branch
    )


def _delete_empty_branch(vault_dir: Path, ctx: RunContext) -> CompleteResult:
    """Issue #250: a constrained exit (rc=1) that committed nothing.

    There is no per-cycle history to lose, so unlike ``_squash_merge``'s
    ``delete_branch=False`` path this doesn't retain anything for review —
    it checks ``ctx.base_branch`` back out and drops ``ctx.branch``,
    exactly like the rc=0 clean-merge path's branch cleanup.
    """
    try:
        _git(vault_dir, "checkout", ctx.base_branch)
    except subprocess.CalledProcessError as exc:
        err = _short_err(exc)
        _LOG.warning(
            "vault_commit: could not check out %s to drop empty branch %s: %s",
            ctx.base_branch,
            ctx.branch,
            err,
        )
        return CompleteResult(
            ok=False, branch_retained=True, error=err, branch=ctx.branch
        )
    try:
        # `-d`, not `-D`: git itself refuses when the branch holds a commit
        # the base branch (now HEAD) does not.
        _git(vault_dir, "branch", "-d", ctx.branch)
    except subprocess.CalledProcessError as exc:
        _LOG.warning(
            "vault_commit: failed to delete empty branch %s: %s",
            ctx.branch,
            _short_err(exc),
        )
        return CompleteResult(ok=True, branch_retained=True, branch=ctx.branch)
    _LOG.info(
        "vault_commit: run ended rc=1 with no commits; dropped empty branch %s, "
        "back on %s",
        ctx.branch,
        ctx.base_branch,
    )
    return CompleteResult(ok=True, merged=False, branch_retained=False, branch=None)


def _rewind_aborted_tail(vault_dir: Path, ctx: RunContext) -> CompleteResult:
    """When a cycle aborts (rc=2), the partial work is unreliable.

    Undo the commit the aborted cycle itself made — the one the
    ``commit_cycle`` call right before this recorded — by resetting to the
    tip it started from. Nothing else is ours to rewind: when that call
    committed nothing (an abort before anything tracked was written has no
    diff; a failed commit leaves the work uncommitted) the tip is the
    previous, good cycle, and when the tip is not the commit we made (the
    user committed mid-run) it is theirs. Both are left alone.
    """
    retained = CompleteResult(ok=True, branch_retained=True, branch=ctx.branch)
    made = ctx.last_cycle_commit
    if made is None:
        return retained
    head_result = _git(vault_dir, "rev-parse", "HEAD", check=False)
    head = head_result.stdout.strip()
    if head != made.sha:
        return retained
    try:
        # The recorded tip rather than `HEAD~1`: a same-cycle re-emit amends
        # HEAD (spec 062 FR2), and the parent of an amended commit is one
        # commit further back than the cycle's earlier, good content.
        _git(vault_dir, "reset", "--hard", made.head_before)
        ctx.cycle_commit_shas = list(made.shas_before)
        ctx.last_cycle_commit = None
        _write_state(vault_dir, ctx)
        _LOG.info(
            "vault_commit: rewound aborted cycle commit %s on %s",
            head,
            ctx.branch,
        )
    except subprocess.CalledProcessError as exc:
        _LOG.warning(
            "vault_commit: rewind failed on aborted cycle: %s",
            _short_err(exc),
        )
    return retained


def _should_push(vault_dir: Path, policy: object) -> bool:
    """Resolve the push-on-complete policy against the actual remote state.

    *policy* is whatever YAML produced for ``vault_commit.push_on_complete``,
    not necessarily one of the three documented strings. A push is the one
    step here that cannot be taken back, so nothing resolves to "push" by
    default: YAML's boolean spellings of "no" (``false`` / ``no`` / ``off``)
    mean ``never``, and a value that is not a known policy — a typo, an empty
    key — skips the push with a WARNING rather than falling through to
    ``auto``. ``true`` / ``yes`` / ``on`` keep meaning ``auto``.
    """
    if policy is True:
        policy = "auto"
    elif policy is False:
        policy = "never"
    elif isinstance(policy, str):
        policy = policy.strip().lower()
    if policy == "never":
        return False
    if policy not in ("auto", "always"):
        _LOG.warning(
            "vault_commit: push_on_complete=%r is not one of auto | never | "
            "always; not pushing",
            policy,
        )
        return False
    has_remote = _has_remote(vault_dir)
    if policy == "always" and not has_remote:
        _LOG.warning(
            "vault_commit: push_on_complete=always but no remote configured; skipping"
        )
    return has_remote


def _push(vault_dir: Path, branch: str) -> tuple[bool, str]:
    """Push ``branch`` to the first remote. Returns (ok, error_msg)."""
    try:
        remote_result = _git(vault_dir, "remote")
        remotes = [r for r in remote_result.stdout.split() if r]
        if not remotes:
            return False, "no remote"
        _git(vault_dir, "push", remotes[0], branch)
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, _short_err(exc)


# ---------------------------------------------------------------------------
# Sidecars + utilities
# ---------------------------------------------------------------------------


def _emit_sidecar(
    vault_dir: Path,
    label: str,
    *,
    stage: str,
    error: str,
) -> None:
    """Persist a small JSON sidecar describing a commit failure.

    Lives under ``_pipeline/commit-failures-<label>.json``. Best-effort —
    if even the sidecar write fails we just swallow.
    """
    try:
        path = vault_dir / "_pipeline" / f"commit-failures-{label}.json"
        payload = {
            "label": label,
            "stage": stage,
            "error": error,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        write_json(path, payload)
    except Exception:  # pragma: no cover - sidecar is best-effort
        pass


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _short_err(exc: subprocess.CalledProcessError) -> str:
    """Best-effort one-line summary of a CalledProcessError for logs."""
    raw = (exc.stderr or "") + (exc.stdout or "")
    raw = _CTRL_RE.sub("", raw).strip()
    if not raw:
        raw = str(exc)
    # Keep things tractable in log files.
    if len(raw) > 240:
        raw = raw[:237] + "..."
    return raw
