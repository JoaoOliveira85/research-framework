"""Move an existing vault's durable state under ``_pipeline/state/`` (spec 083)
and convert its Markdown backlog into the structured store (spec 084).

``MIGRATION_STEPS`` is an ordered list of idempotent steps. A step has
``plan(vault) -> StepPlan`` (reads, never writes) and ``apply(vault, plan)``.
A later spec adds a step by appending one entry to the list.

The 083 step moves every state artefact the registry marks ``moved_by_083``,
byte for byte (nothing is regenerated or rewritten, so hand-set priorities in
``coverage-targets.json`` survive), fixes the vault's ``.gitignore``, and
backfills the cycle ledger. Every move is checked before any is made. In a git
repository the result lands as one ``framework: migrate _pipeline layout``
commit holding only what the migration touched.

The 084 step runs after it: an unconverted vault (store absent, a Markdown
backlog without the view's footer present) gets the store, the byte-for-byte
archive and a rendered view in place of the Markdown, which leaves the git
index. It lands as its own ``framework: convert the research backlog to a
store`` commit, after the layout move's. Each step commits what it changed
before the next one starts, so the commits stay separate.

The 087 step runs third: every corpus note that lacks ``as_of`` or ``currency``
gets the missing line(s), added surgically, in its own ``framework: stamp note
currency`` commit holding only those notes. It is not a layout change, so an
unstamped vault is NOT legacy: ``state_layout.legacy_paths_present`` and
``require_migrated`` never look at it, because a note without the fields reads
as ``current`` and never due (spec 087 FR-006), and refusing runs over it would
be wrong. The step never queues review work; the due sweep does that, a cycle
at a time, bounded by the cycle split.
"""

from __future__ import annotations

import datetime
import filecmp
import logging
import os
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..generator.scaffold import _render_vault_gitignore
from ..vault.corpus import corpus_dir
from . import (
    backlog,
    backlog_conversion,
    currency_stamp,
    cycle_ledger,
    state_layout,
    vault_commit,
)

_LOG = logging.getLogger(__name__)

COMMIT_TITLE = "migrate _pipeline layout"
BACKLOG_COMMIT_TITLE = "convert the research backlog to a store"
STAMP_COMMIT_TITLE = "stamp note currency"
ALREADY_MIGRATED = "already migrated"

# The marker line that opens the ``_pipeline`` stanza in every rendering, and
# the stanza the 2.0.x scaffold wrote (``_render_vault_gitignore`` before 083).
_STANZA_MARKER = "# `_pipeline/` is regenerable EXCEPT"
# The Markdown backlog's path before 084, from the registry (spelled once).
_LEGACY_BACKLOG = next(
    a.legacy_rel for a in state_layout.STATE_ARTEFACTS if a.name == "research_backlog"
)
_LEGACY_STANZA = (
    "# `_pipeline/` is regenerable EXCEPT the two control files below. Git\n"
    "# cannot re-include a path under an excluded directory, hence the\n"
    "# un-ignore / re-exclude / un-exclude sequence.\n"
    "!_pipeline/\n"
    "_pipeline/*\n"
    f"!{_LEGACY_BACKLOG}\n"
    "!_pipeline/coverage-targets.json\n"
)
_REINCLUDE_LINES = (
    f"!{state_layout.STATE_DIR}/",
    f"{state_layout.STATE_DIR}/*.db-wal",
    f"{state_layout.STATE_DIR}/*.db-shm",
)

_LEGACY_SETTINGS = f"{state_layout.PIPELINE_DIR}/settings.yaml"


class MigrationError(RuntimeError):
    """The migration refused or stopped; nothing was changed unless said so."""


@dataclass(frozen=True)
class Move:
    src: str  # vault-relative POSIX
    dst: str


@dataclass(frozen=True)
class GitignoreChange:
    new_text: str
    description: str


@dataclass(frozen=True)
class StepCommit:
    """What a step's own commit holds (``vault_commit.commit_framework_change``)."""

    title: str
    body: str
    paths: list[str]
    no_add: list[str] = field(default_factory=list)
    """In the commit's pathspec but never staged with ``git add`` (a path the
    step already removed from the index)."""


@dataclass
class StepPlan:
    step: str
    moves: list[Move] = field(default_factory=list)
    duplicates: list[Move] = field(default_factory=list)
    """Legacy copies whose destination already holds identical bytes: removed."""
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    gitignore: GitignoreChange | None = None
    backfill_rows: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    """Reasons the step cannot run; any error stops the migration (exit 2)."""
    commit: StepCommit | None = None
    conversion: backlog_conversion.ConversionResult | None = None
    legacy_bytes: bytes | None = None
    stamps: currency_stamp.StampPlan | None = None

    @property
    def is_noop(self) -> bool:
        return not (
            self.moves
            or self.duplicates
            or self.gitignore
            or self.backfill_rows
            or self.conversion
            or (self.stamps is not None and self.stamps.stamps)
        )


@dataclass(frozen=True)
class MigrationStep:
    name: str
    plan: Callable[[Path], StepPlan]
    apply: Callable[[Path, StepPlan], None]


@dataclass
class MigrationResult:
    exit_code: int
    messages: list[str] = field(default_factory=list)
    committed: str | None = None
    """The last commit made (``None`` when nothing was committed)."""
    commits: list[str] = field(default_factory=list)
    migrated: bool = False


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def _git(vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=False
    )


def _is_git(vault: Path) -> bool:
    return vault_commit._is_git_repo(vault)


def _is_tracked(vault: Path, rel: str) -> bool:
    return _git(vault, "ls-files", "--error-unmatch", "--", rel).returncode == 0


# ---------------------------------------------------------------------------
# Step: move state into _pipeline/state/
# ---------------------------------------------------------------------------


def _files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _legacy_pairs(vault: Path) -> list[Move]:
    """Every (legacy, new) file pair for the rows this spec moves."""
    pairs: list[Move] = []
    for art in state_layout.STATE_ARTEFACTS:
        if not art.moved_by_083 or not art.legacy_rel:
            continue
        if art.kind == "per_module_file":
            prefix, suffix = art.legacy_rel.split("<module>/", 1)
            new_prefix, new_suffix = art.new_rel.split("<module>/", 1)
            parent = vault / prefix
            if not parent.is_dir():
                continue
            for module in sorted(parent.iterdir()):
                if (module / suffix).is_file():
                    pairs.append(
                        Move(
                            f"{prefix}{module.name}/{suffix}",
                            f"{new_prefix}{module.name}/{new_suffix}",
                        )
                    )
        elif art.kind == "dir":
            root = vault / art.legacy_rel
            if root.is_dir():
                for f in _files_under(root):
                    rel = f.relative_to(root).as_posix()
                    pairs.append(Move(art.legacy_rel + rel, art.new_rel + rel))
        else:
            if (vault / art.legacy_rel).is_file():
                pairs.append(Move(art.legacy_rel, art.new_rel))
    return pairs


def _sqlite_sidecars(vault: Path) -> list[str]:
    base = next(
        a.legacy_rel for a in state_layout.STATE_ARTEFACTS if a.name == "sources_db"
    )
    return [
        base + suffix
        for suffix in state_layout.SQLITE_SIDECAR_SUFFIXES
        if (vault / (base + suffix)).exists()
    ]


def _plan_gitignore(vault: Path) -> GitignoreChange | None:
    path = vault / ".gitignore"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^!(.+)/\*\*$", text, re.MULTILINE)
    corpus = m.group(1) if m else "data_vault"
    shipped_new = _render_vault_gitignore(corpus)
    if text == shipped_new:
        return None
    head = shipped_new[: shipped_new.index(_STANZA_MARKER)]
    if text == head + _LEGACY_STANZA:
        return GitignoreChange(
            shipped_new, "replace the _pipeline stanza with the shipped rendering"
        )
    if _LEGACY_STANZA in text:
        # The shipped stanza, untouched, inside a file the operator added lines
        # to (a feed catalogue re-include, a secrets pattern). Replace the
        # stanza where it stands and keep every other line byte for byte:
        # appending the re-includes instead would leave the stanza's per-file
        # lines behind, and they would keep un-ignoring files the layout has
        # since moved or turned into ignored views.
        before, _, after = text.partition(_LEGACY_STANZA)
        return GitignoreChange(
            before + shipped_new[len(head) :] + after,
            "replace the _pipeline stanza in place; the other lines are kept",
        )
    present = {ln.strip() for ln in text.splitlines()}
    missing = [ln for ln in _REINCLUDE_LINES if ln not in present]
    if not missing:
        return None
    suffix = "" if text.endswith("\n") or not text else "\n"
    return GitignoreChange(
        text
        + suffix
        + "# Added by `migrate-layout` (spec 083): track _pipeline/state/.\n"
        + "".join(f"{ln}\n" for ln in missing),
        "customised .gitignore: append " + ", ".join(missing),
    )


def _plan_move_state(vault: Path) -> StepPlan:
    plan = StepPlan("move_state_into_state_dir")
    for pair in _legacy_pairs(vault):
        dst = vault / pair.dst
        if not dst.exists():
            plan.moves.append(pair)
        elif dst.is_file() and filecmp.cmp(vault / pair.src, dst, shallow=False):
            plan.duplicates.append(pair)
        else:
            plan.conflicts.append((pair.src, pair.dst))
    plan.gitignore = _plan_gitignore(vault)
    plan.backfill_rows = cycle_ledger.pending_backfill(vault)
    tracked_sources = (
        [
            m.src
            for m in plan.moves + plan.duplicates
            if _is_git(vault) and _is_tracked(vault, m.src)
        ]
        if _is_git(vault)
        else []
    )
    plan.commit = StepCommit(
        COMMIT_TITLE,
        "Move durable state under _pipeline/state/ (spec 083); "
        "back-fill the cycle ledger.",
        [".gitignore", state_layout.STATE_DIR, *sorted(set(tracked_sources))],
    )
    if (vault / _LEGACY_SETTINGS).is_file():
        plan.warnings.append(
            f"{_LEGACY_SETTINGS} is an operator override this layout does not "
            "move; fold its keys into the vault-root settings.yaml (spec 076 "
            "owns it)"
        )
    return plan


def _checkpoint_legacy_db(vault: Path, rel: str) -> None:
    db = vault / rel
    try:
        conn = sqlite3.connect(db)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise MigrationError(f"could not checkpoint {rel}: {exc}") from exc


def _prune_empty_dirs(vault: Path, rel: str) -> None:
    parent = (vault / rel).parent
    stop = vault / state_layout.PIPELINE_DIR
    while parent != stop and parent != vault:
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _apply_move_state(vault: Path, plan: StepPlan) -> None:
    git = _is_git(vault)
    # The ignore file first, so `git add` of a moved file is not refused.
    if plan.gitignore is not None:
        original = (vault / ".gitignore").read_text(encoding="utf-8")
        (vault / ".gitignore").write_text(plan.gitignore.new_text, encoding="utf-8")
    if git:
        # Verify before moving anything: if a rule still hides the state
        # directory, put the ignore file back and stop with the tree untouched.
        problems = _verify_not_ignored(
            vault, [m.dst for m in plan.moves + plan.duplicates]
        )
        if problems:
            if plan.gitignore is not None:
                (vault / ".gitignore").write_text(original, encoding="utf-8")
            raise MigrationError(
                "git would still ignore _pipeline/state/ after the .gitignore "
                "change, so nothing was moved. The winning rule:\n  "
                + "\n  ".join(problems)
            )
    sources_db = next(
        a.legacy_rel for a in state_layout.STATE_ARTEFACTS if a.name == "sources_db"
    )
    if any(m.src == sources_db for m in plan.moves + plan.duplicates):
        _checkpoint_legacy_db(vault, sources_db)
        for side in _sqlite_sidecars(vault):  # empty after the checkpoint
            (vault / side).unlink()
    for move in plan.duplicates:
        tracked = git and _is_tracked(vault, move.src)
        if tracked:
            _git(vault, "rm", "-q", "--cached", "--", move.src)
        (vault / move.src).unlink()
        _prune_empty_dirs(vault, move.src)
    for move in plan.moves:
        dst = vault / move.dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        if git and _is_tracked(vault, move.src):
            result = _git(vault, "mv", "--", move.src, move.dst)
            if result.returncode != 0:
                raise MigrationError(
                    f"git mv {move.src} {move.dst} failed: {result.stderr.strip()}"
                )
        else:
            os.rename(vault / move.src, dst)
        _prune_empty_dirs(vault, move.src)
    cycle_ledger.backfill_from_cycles(vault)


MOVE_STATE_STEP = MigrationStep(
    "move_state_into_state_dir", _plan_move_state, _apply_move_state
)


# ---------------------------------------------------------------------------
# Step: convert the Markdown backlog into the structured store (spec 084)
# ---------------------------------------------------------------------------


def _plan_convert_backlog(vault: Path) -> StepPlan:
    plan = StepPlan("convert_backlog_to_store")
    if not backlog.is_unconverted(vault):
        return plan  # already converted, or no backlog at all
    legacy = backlog.view_path(vault)
    rel = legacy.relative_to(vault).as_posix()
    raw = legacy.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        plan.errors.append(
            f"{rel} is not valid UTF-8 ({exc}); the research backlog was not converted"
        )
        return plan
    plan.legacy_bytes = raw
    plan.conversion = backlog_conversion.convert_legacy(
        text, today=datetime.datetime.now(datetime.UTC).date().isoformat()
    )
    store = backlog.store_path(vault).relative_to(vault).as_posix()
    archive = (
        state_layout.research_backlog_archive_path(vault).relative_to(vault).as_posix()
    )
    paths = [store, archive]
    no_add: list[str] = []
    if _is_git(vault) and _is_tracked(vault, rel):
        paths.append(rel)
        no_add.append(rel)
    plan.commit = StepCommit(
        BACKLOG_COMMIT_TITLE,
        f"Convert the Markdown backlog into {store} (spec 084); the original is kept at "
        f"{archive}, and {rel} is now a rendered view that git ignores.",
        paths,
        no_add,
    )
    return plan


def _apply_convert_backlog(vault: Path, plan: StepPlan) -> None:
    assert plan.conversion is not None and plan.legacy_bytes is not None
    rel = backlog.view_path(vault).relative_to(vault).as_posix()
    try:
        backlog_conversion.write_converted(
            vault, plan.conversion, original=plan.legacy_bytes
        )
    except (OSError, ValueError) as exc:
        raise MigrationError(f"could not convert the research backlog: {exc}") from exc
    if _is_git(vault) and _is_tracked(vault, rel):
        result = _git(vault, "rm", "-q", "--cached", "--", rel)
        if result.returncode != 0:
            raise MigrationError(
                f"git rm --cached {rel} failed: {result.stderr.strip()}"
            )


CONVERT_BACKLOG_STEP = MigrationStep(
    "convert_backlog_to_store", _plan_convert_backlog, _apply_convert_backlog
)

# ---------------------------------------------------------------------------
# Step: stamp as_of and currency onto existing notes (spec 087)
# ---------------------------------------------------------------------------

# One `git add -- <path>...` and one `git commit -- <path>...` carry every path
# on the command line; past this many bytes the commit names the corpus
# directory instead (the tree is clean when the step runs, so it holds the same
# notes), or the shell's argument limit would refuse it.
_PATHSPEC_LIMIT = 150_000


def _plan_stamp_note_currency(vault: Path) -> StepPlan:
    plan = StepPlan("stamp_note_currency")
    stamps = currency_stamp.plan_stamps(vault)
    if not stamps.stamps:
        return plan
    plan.stamps = stamps
    paths = [s.rel for s in stamps.stamps]
    if sum(len(p) + 1 for p in paths) > _PATHSPEC_LIMIT:
        paths = [corpus_dir(vault).relative_to(vault).as_posix()]
    plan.commit = StepCommit(
        STAMP_COMMIT_TITLE,
        f"Stamp as_of and currency on {len(stamps.stamps)} existing note(s) "
        f"(spec 087): as_of from {stamps.oldest} to {stamps.newest}, taken from "
        "each note's own source dates, else its updated or created date, else "
        "its first commit; currency: current. Every other line of every note is "
        "unchanged.",
        paths,
    )
    return plan


def _apply_stamp_note_currency(vault: Path, plan: StepPlan) -> None:
    assert plan.stamps is not None
    written = currency_stamp.apply_stamps(vault, plan.stamps)
    _LOG.info(
        "migrate-layout: stamped %d note(s) with as_of and currency, skipped %d; "
        "as_of from %s to %s",
        written,
        plan.stamps.skipped,
        plan.stamps.oldest,
        plan.stamps.newest,
    )


STAMP_NOTE_CURRENCY_STEP = MigrationStep(
    "stamp_note_currency", _plan_stamp_note_currency, _apply_stamp_note_currency
)

# Ordered; a later spec appends its step here.
MIGRATION_STEPS: list[MigrationStep] = [
    MOVE_STATE_STEP,
    CONVERT_BACKLOG_STEP,
    STAMP_NOTE_CURRENCY_STEP,
]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _verify_not_ignored(vault: Path, rels: list[str]) -> list[str]:
    """Return one line per path git still ignores, naming the winning rule."""
    problems: list[str] = []
    probes = sorted(
        set(rels)
        | {state_layout.cycle_ledger_path(vault).relative_to(vault).as_posix()}
    )
    for rel in probes:
        result = _git(vault, "check-ignore", "-v", "--no-index", "--", rel)
        if result.returncode == 0:
            problems.append(f"{rel} is still ignored by {result.stdout.strip()}")
    return problems


def _describe(plan: StepPlan) -> list[str]:
    lines = [f"step {plan.step}:"]
    lines += [f"  move {m.src} -> {m.dst}" for m in plan.moves]
    lines += [
        f"  drop legacy copy {m.src} (identical to {m.dst})" for m in plan.duplicates
    ]
    lines += [f"  CONFLICT {src} and {dst} differ" for src, dst in plan.conflicts]
    if plan.gitignore is not None:
        lines.append(f"  .gitignore: {plan.gitignore.description}")
    if plan.backfill_rows:
        lines.append(f"  cycle ledger: backfill {plan.backfill_rows} row(s)")
    if plan.conversion is not None:
        archive = state_layout.research_backlog_archive_path(Path()).as_posix()
        lines.append(
            "  convert the Markdown backlog into "
            f"{state_layout.research_backlog_path(Path()).as_posix()}"
        )
        lines.append("  " + plan.conversion.info_line(archive))
    if plan.stamps is not None and plan.stamps.stamps:
        stamps = plan.stamps
        lines.append(
            f"  stamp {len(stamps.stamps)} note(s) with as_of and currency "
            f"(as_of from {stamps.oldest} to {stamps.newest}); "
            f"skip {stamps.skipped} (no frontmatter, or it does not parse)"
        )
    lines += [f"  error: {e}" for e in plan.errors]
    lines += [f"  warning: {w}" for w in plan.warnings]
    return lines


def migrate(
    vault: Path, *, dry_run: bool = False, force: bool = False
) -> MigrationResult:
    """Run every migration step on ``vault``. Exit code 0 ok, 2 refused."""
    result = MigrationResult(0)
    say = result.messages.append
    if not vault.is_dir():
        say(f"error: vault not found: {vault}")
        result.exit_code = 2
        return result

    plans = [(step, step.plan(vault)) for step in MIGRATION_STEPS]
    conflicts = [c for _, plan in plans for c in plan.conflicts]
    errors = [e for _, plan in plans for e in plan.errors]
    for _, plan in plans:
        for warning in plan.warnings:
            _LOG.warning("migrate-layout: %s", warning)

    if dry_run:
        for _, plan in plans:
            result.messages.extend(_describe(plan))
        if conflicts or errors:
            result.exit_code = 2
        if all(plan.is_noop for _, plan in plans) and not conflicts and not errors:
            say(f"{ALREADY_MIGRATED}: nothing to do")
        else:
            say("dry-run: nothing was changed")
        return result

    if errors:
        result.messages += [f"error: {e}" for e in errors]
        result.exit_code = 2
        return result

    if conflicts:
        say(
            "error: refusing to migrate; both the legacy and the new path exist "
            "with different content (nothing was moved):"
        )
        result.messages += [f"  {src}  vs  {dst}" for src, dst in conflicts]
        result.exit_code = 2
        return result

    if all(plan.is_noop for _, plan in plans):
        say(f"{ALREADY_MIGRATED}: nothing to do")
        return result

    git = _is_git(vault)
    committing = git and bool(vault_commit._load_settings(vault)["enabled"])
    if git and not force and vault_commit.is_working_tree_dirty(vault):
        say(
            "error: the working tree has uncommitted changes. Commit or stash "
            "them, or re-run with --force."
        )
        result.exit_code = 2
        return result

    try:
        for step, plan in plans:
            if plan.is_noop:
                continue
            step.apply(vault, plan)
            result.migrated = True
            if not git:
                continue
            if not committing:
                continue
            if plan.commit is None:
                continue
            commit = vault_commit.commit_framework_change(
                vault,
                title=plan.commit.title,
                body=plan.commit.body,
                paths=plan.commit.paths,
                no_add=plan.commit.no_add,
            )
            if not commit.ok:
                say(
                    f"error: the {step.name} step ran but the commit failed: {commit.error}"
                )
                result.exit_code = 2
                return result
            if commit.sha:
                result.commits.append(commit.sha)
                result.committed = commit.sha
                say(f"{step.name}: committed {commit.sha}")
    except MigrationError as exc:
        say(f"error: {exc}")
        result.exit_code = 2
        return result

    if not git:
        _LOG.info(
            "migrate-layout: not a git repository; files moved, nothing committed"
        )
        say("moved on disk; not a git repository, nothing committed")
    elif not committing:
        _LOG.info(
            "migrate-layout: vault_commit.enabled is false; files moved, nothing committed"
        )
        say("moved on disk; vault_commit is disabled, nothing committed")
    else:
        say(
            f"migrated: committed {result.committed}"
            if result.committed
            else "migrated"
        )
    for _, plan in plans:
        result.messages += [f"warning: {w}" for w in plan.warnings]
    return result
