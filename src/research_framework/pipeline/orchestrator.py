"""Phase 2 cycle orchestrator — drives `run_cycle_steps` and reads exit codes.

Constitution: the orchestrator does NOT self-assess. It reads script exit codes only.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

if TYPE_CHECKING:
    from ..cli._budget_resolve import BudgetResolution

from ..spec.schema import SpecConfig
from . import plan_narrator, quality_report, research_plan, vault_commit, vault_git
from .atomic_write import write_json, write_text
from .correction import build_directive
from .coverage import (
    all_targets_met,
    existing_vault_filenames,
    merge_expected_filenames_from_scan,
    unmet_expected_filenames,
    unmet_targets,
    update_after_cycle,
)
from .cycle_runner import run_cycle_steps
from .cycle_summary import write_summary as _write_cycle_summary
from .gates import GateResult, run_gate
from .gates_cycle import CG001_min_cycle_yield
from .gates_step import SG005_frontmatter_completeness
from .run_report import write_run_report as _write_run_report
from .stubs import scan_stubs

_LOG = logging.getLogger(__name__)

BUDGET_LOG_REL = Path("_pipeline") / "budget-log.md"


def _parse_note_created_at_cycle(note_path: Path) -> int | None:
    try:
        fm, _body = parse_frontmatter(note_path)
    except (OSError, FrontmatterParseError):
        return None
    if not fm:
        return None
    life = fm.get("lifecycle")
    if not isinstance(life, dict):
        return None
    raw = life.get("created_at_cycle")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _batch_notes_written_union(vault_dir: Path, cycle_num: int) -> set[str]:
    """Filenames / relative paths already recorded in batch JSON for this cycle."""
    cdir = vault_dir / "_pipeline" / "cycles"
    if not cdir.is_dir():
        return set()
    prefix = f"cycle-{cycle_num:03d}-batch-"
    out: set[str] = set()
    for p in sorted(cdir.glob(f"{prefix}*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for raw in doc.get("notes_written") or []:
            s = str(raw).strip().replace("\\", "/")
            if not s:
                continue
            out.add(s)
            out.add(Path(s).name)
    return out


def _next_batch_number(vault_dir: Path, cycle_num: int) -> int:
    cdir = vault_dir / "_pipeline" / "cycles"
    if not cdir.is_dir():
        return 1
    prefix = f"cycle-{cycle_num:03d}-batch-"
    highest = 0
    for p in cdir.glob(f"{prefix}*.json"):
        stem = p.stem
        try:
            bn = int(stem.rsplit("-", maxsplit=1)[-1])
        except ValueError:
            continue
        highest = max(highest, bn)
    return highest + 1


def _free_quarantine_path(qdir: Path, note_path: Path) -> Path:
    """``qdir/<name>``, or the first free ``<stem>-<n><suffix>``.

    Quarantine is often the only copy of a note, and ``rename`` replaces an
    existing target silently — every move into ``qdir`` goes through here.
    """
    dest = qdir / note_path.name
    i = 1
    while dest.exists():
        dest = qdir / f"{note_path.stem}-{i}{note_path.suffix}"
        i += 1
    return dest


def _quarantine_orphan_note(vault_dir: Path, note_path: Path) -> None:
    qdir = vault_dir / "_pipeline" / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    dest = _free_quarantine_path(qdir, note_path)
    shutil.move(str(note_path), str(dest))


def _reconcile_orphan_notes_at_cycle_start(vault_dir: Path, cycle_num: int) -> None:
    """R-001 / T058: resume after crash — accept or quarantine un-acknowledged notes."""
    data_vault = corpus_dir(vault_dir)
    if not data_vault.is_dir():
        return
    acknowledged = _batch_notes_written_union(vault_dir, cycle_num)
    orphan_paths: list[Path] = []
    for path in sorted(data_vault.rglob("*.md")):
        if path.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        try:
            rel = path.relative_to(data_vault)
        except ValueError:
            continue
        if "_templates" in rel.parts:
            continue
        if _parse_note_created_at_cycle(path) != cycle_num:
            continue
        rel_posix = rel.as_posix()
        if rel_posix in acknowledged or path.name in acknowledged:
            continue
        orphan_paths.append(path)

    if not orphan_paths:
        return

    accepted: list[Path] = []
    for p in orphan_paths:
        sg = SG005_frontmatter_completeness([p])
        if sg.status == "FAIL":
            _LOG.info(
                f"WARN: orphan note {p.name} failed SG-005 — moving to "
                f"_pipeline/quarantine: {sg.message}"
            )
            try:
                _quarantine_orphan_note(vault_dir, p)
            except OSError as exc:
                _LOG.warning(f"WARN: could not quarantine {p.name}: {exc}")
            continue
        accepted.append(p)

    if not accepted:
        return

    cycles_dir = vault_dir / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    batch_n = _next_batch_number(vault_dir, cycle_num)
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    sg_batch = SG005_frontmatter_completeness(sorted(accepted))
    notes_written = sorted(p.name for p in accepted)
    doc: dict = {
        "schema_version": "1",
        "cycle_number": cycle_num,
        "batch_number": batch_n,
        "started_at": ts,
        "finished_at": ts,
        "topics": [],
        "notes_written": notes_written,
        "skipped_topics": [],
        "sg_gate_results": [sg_batch.to_dict()],
        "accepted": True,
        "correction_directive_in": "resumed_from_crash",
    }
    write_json(cycles_dir / f"cycle-{cycle_num:03d}-batch-{batch_n:03d}.json", doc)


def _rebuild_indexes_best_effort(vault_dir: Path) -> None:
    try:
        from research_framework.vault import indexer

        indexer.rebuild_all(vault_dir)
    except Exception as exc:
        _LOG.warning(f"[orchestrator] WARN: indexer.rebuild_all failed: {exc}")


def _quarantine_out_of_scope_notes(vault_dir: Path, spec) -> list[str]:
    """Move notes whose filename / category / title / body matches a `scope.out_of_scope`
    token into `_pipeline/quarantine/`. Enforces SC-006 against agent disobedience.
    Returns the list of quarantined filenames (empty if none).
    """
    if spec is None:
        return []
    oos = [
        t.lower()
        for t in (getattr(spec.scope, "out_of_scope", None) or [])
        if t.strip()
    ]
    if not oos:
        return []
    corpus = corpus_dir(vault_dir)
    if not corpus.is_dir():
        return []
    quarantine = vault_dir / "_pipeline" / "quarantine"
    quarantined: list[str] = []
    for note in corpus.rglob("*.md"):
        if note.name.startswith("_"):
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        hay = note.name.lower() + "\n" + text[:2000].lower()
        if any(token in hay for token in oos):
            quarantine.mkdir(parents=True, exist_ok=True)
            target = _free_quarantine_path(quarantine, note)
            try:
                note.rename(target)
                quarantined.append(note.name)
                _LOG.info(
                    f"[orchestrator] quarantined out-of-scope note: "
                    f"{note.relative_to(vault_dir)} -> {target.relative_to(vault_dir)}"
                )
            except OSError as exc:
                _LOG.warning(f"[orchestrator] WARN: could not quarantine {note}: {exc}")
    return quarantined


def _first_verifier_note(fm: dict) -> str:
    """Best-effort one-line reason from a note's ``verifier_notes`` for the backlog."""
    raw = fm.get("verifier_notes")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    text = str(raw or "").strip().splitlines()
    return text[0].strip() if text else "no reason recorded"


_QUARANTINE_BLOCK_START = "<!-- quarantine -->"
_QUARANTINE_BLOCK_END = "<!-- /quarantine -->"
_QUARANTINE_STEM_RE = re.compile(r"<!-- stem:(\S+) -->\s*$")


def _quarantine_pointer_line(note_stem: str, *, restored: bool, reason: str) -> str:
    """One research-backlog bullet for a quarantined note.

    The trailing ``<!-- stem:... -->`` tag (invisible in rendered markdown) is
    how :func:`_reconcile_quarantine_block` matches a pointer back to its
    quarantine file across sweeps (#257) without having to remember, at
    reconciliation time, whether the note was a brand-new quarantine or a
    restored refresh.
    """
    if restored:
        text = (
            f"- [ ] retry refresh of {note_stem} — previous content restored, "
            f"rejected draft quarantined (verifier_status: rejected — {reason})"
        )
    else:
        text = (
            f"- [ ] rewrite quarantined note: {note_stem} "
            f"(verifier_status: rejected — {reason})"
        )
    return f"{text} <!-- stem:{note_stem} -->\n"


def _extract_managed_block(text: str, start: str, end: str) -> str | None:
    """Return a ``start``/``end`` delimited block's inner text, or None if absent."""
    if start not in text or end not in text:
        return None
    _, _, rest = text.partition(start)
    inner, _, _ = rest.partition(end)
    return inner.strip("\n")


def _replace_managed_block(text: str, start: str, end: str, body: str) -> str:
    """Insert, replace, or remove a ``start``/``end`` delimited block in ``text``.

    Mirrors ``scripts/topic_harvest.py``'s per-cycle managed block: content
    outside the block — an operator's own manual backlog entries — is always
    left untouched. An empty ``body`` removes the block entirely rather than
    leaving an empty marker pair behind, which is how #257's "clear when the
    quarantine empties" is satisfied.
    """
    has_block = start in text and end in text
    if not body:
        if not has_block:
            return text
        pre, _, rest = text.partition(start)
        _, _, post = rest.partition(end)
        return pre.rstrip("\n") + ("\n" if pre.strip() else "") + post.lstrip("\n")
    wrapped = f"{start}\n{body}\n{end}\n"
    if has_block:
        pre, _, rest = text.partition(start)
        _, _, post = rest.partition(end)
        return pre.rstrip("\n") + "\n\n" + wrapped + post.lstrip("\n")
    sep = "" if not text or text.endswith("\n") else "\n"
    return text + sep + wrapped


def _reconcile_quarantine_block(
    backlog_text: str, quarantine_dir: Path, new_lines: list[str]
) -> str:
    """Merge ``new_lines`` into the backlog's ``quarantine`` managed block.

    Any previously-recorded pointer whose quarantine file no longer exists is
    dropped — a note reinstated via ``./vault re-grade`` or fixed by hand
    clears its own pointer on the next sweep instead of the backlog growing
    forever (#257). Collision-renamed quarantine copies (``<stem>-<n>.md``,
    written when two same-named notes are quarantined in one sweep) are a
    known gap: reconciliation matches on the *original* stem, which such a
    copy no longer carries.
    """
    live_stems = (
        {p.stem for p in quarantine_dir.glob("*.md")}
        if quarantine_dir.is_dir()
        else set()
    )
    existing = _extract_managed_block(
        backlog_text, _QUARANTINE_BLOCK_START, _QUARANTINE_BLOCK_END
    )
    kept_lines: list[str] = []
    known_stems: set[str] = set()
    for line in (existing or "").splitlines(keepends=True):
        match = _QUARANTINE_STEM_RE.search(line)
        if match and match.group(1) in live_stems:
            kept_lines.append(line if line.endswith("\n") else line + "\n")
            known_stems.add(match.group(1))
    for line in new_lines:
        match = _QUARANTINE_STEM_RE.search(line)
        if match and match.group(1) not in known_stems:
            kept_lines.append(line)
            known_stems.add(match.group(1))
    body = "".join(kept_lines).rstrip("\n")
    return _replace_managed_block(
        backlog_text, _QUARANTINE_BLOCK_START, _QUARANTINE_BLOCK_END, body
    )


def _write_quarantine_backlog(
    vault_dir: Path, quarantine_dir: Path, new_lines: list[str]
) -> None:
    """Reconcile the backlog's quarantine block against ``quarantine_dir`` and
    persist any change. Best-effort — a write failure here must not abort the
    cycle (spec 062 FR1)."""
    backlog = vault_dir / "_pipeline" / "research-backlog.md"
    try:
        current = backlog.read_text(encoding="utf-8") if backlog.exists() else ""
        updated = _reconcile_quarantine_block(current, quarantine_dir, new_lines)
        if updated == current:
            return
        backlog.parent.mkdir(parents=True, exist_ok=True)
        write_text(backlog, updated)
    except OSError as exc:  # pragma: no cover - defensive
        _LOG.warning(
            f"[orchestrator] WARN: backlog pointer reconciliation failed: {exc}"
        )


def _quarantine_rejected_notes(vault_dir: Path) -> int:
    """Spec 062 FR1: move every still-``verifier_status: rejected`` note out of the
    indexed/citable corpus into ``_pipeline/quarantine/`` on ANY exit.

    Mirrors :func:`_quarantine_out_of_scope_notes`. The indexer/readers only scan
    ``data_vault/`` (steps/research.py), so a quarantined note becomes uncitable and
    unindexed for free. Each move appends a rewrite pointer to the research backlog
    so the next cycle can fix it. Returns the count quarantined (Principle IX/VIII).

    Clean-exit behaviour is unchanged: the correction/rewrite loop clears rejections
    first, so this sweep finds zero on a clean run.

    A rejected note is one of two things, and they must NOT be treated the same:

    - **New this cycle** — the note-writer created it from scratch. Nothing
      existed before, so moving it out of the corpus loses nothing. Old
      behaviour: quarantine the file as-is.
    - **A rewrite of an already-committed note** — the note-writer overwrote a
      note that existed at the start of the cycle (auto-commit invariant
      guarantees ``HEAD`` was clean then, so ``HEAD`` holds its last-known-good
      body). If we quarantined the file as-is here, the *original* content
      would be gone for good — only the rejected draft would survive, in
      quarantine, uncited. Instead: restore ``HEAD``'s content to the live
      path and quarantine the rejected draft under its own name, so
      ``data_vault/`` never loses a note to a failed refresh.
    """
    corpus = corpus_dir(vault_dir)
    if not corpus.is_dir():
        return 0
    quarantine = vault_dir / "_pipeline" / "quarantine"
    quarantined = 0
    new_backlog_lines: list[str] = []
    for note in sorted(corpus.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        try:
            fm, _body = parse_frontmatter(note)
        except (OSError, FrontmatterParseError):
            continue
        if not fm or str(fm.get("verifier_status", "")).strip().lower() != "rejected":
            continue

        quarantine.mkdir(parents=True, exist_ok=True)
        target = _free_quarantine_path(quarantine, note)

        rel_path = note.relative_to(vault_dir).as_posix()
        previous_content = vault_git.head_content(vault_dir, rel_path)
        restored = False
        if previous_content is None:
            # Brand-new note this cycle — nothing to restore, old behaviour.
            try:
                note.rename(target)
            except OSError as exc:
                _LOG.warning(f"[orchestrator] WARN: could not quarantine {note}: {exc}")
                continue
        else:
            # Rewrite of an already-committed note — quarantine the rejected
            # draft, restore the last committed body to the live path.
            try:
                draft_content = note.read_text(encoding="utf-8")
                target.write_text(draft_content, encoding="utf-8")
                note.write_text(previous_content, encoding="utf-8")
            except OSError as exc:
                _LOG.warning(
                    f"[orchestrator] WARN: could not restore rejected refresh "
                    f"of {note}: {exc}"
                )
                continue
            restored = True

        quarantined += 1
        new_backlog_lines.append(
            _quarantine_pointer_line(
                note.stem, restored=restored, reason=_first_verifier_note(fm)
            )
        )
        if restored:
            _LOG.warning(
                "[orchestrator] rejected refresh of %s reverted to last committed "
                "content; draft quarantined at %s",
                note.relative_to(vault_dir),
                target.relative_to(vault_dir),
            )
        else:
            _LOG.info(
                "[orchestrator] quarantined verifier-rejected note: %s -> %s",
                note.relative_to(vault_dir),
                target.relative_to(vault_dir),
            )
    if quarantined:
        _LOG.warning(
            "[orchestrator] %d verifier-rejected note(s) quarantined "
            "(uncitable/unindexed); see _pipeline/quarantine/",
            quarantined,
        )
    # Reconcile on every sweep, not just when this run quarantined something —
    # a note fixed since the last sweep (e.g. via ./vault re-grade) must have
    # its pointer cleared even on an otherwise-clean exit (#257).
    _write_quarantine_backlog(vault_dir, quarantine, new_backlog_lines)
    return quarantined


def _snapshot_existing_cycle_quality_retry_count(
    vault_dir: Path, cycle_num: int, *, resume: bool
) -> int:
    """If a cycle quality report exists before this run, capture its retry_count."""
    if not resume:
        return 0
    qr = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_num:03d}-quality-report.json"
    )
    if not qr.is_file():
        return 0
    try:
        return int(json.loads(qr.read_text(encoding="utf-8")).get("retry_count") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0


def _restore_cycle_quality_retry_after_report(
    vault_dir: Path,
    cycle_num: int,
    *,
    preserved_retry: int,
    aborted: bool,
    resume: bool,
) -> None:
    """FR-014: ``write_report`` bumps aborted runs to retry_count=2 — restore prior count.

    When resuming after a crash that left a quality report mid-retry, do not
    reset gate memory to the exhaustion cap.
    """
    if not resume or preserved_retry <= 0 or not aborted:
        return
    path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_num:03d}-quality-report.json"
    )
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if int(data.get("retry_count") or 0) == preserved_retry:
        return
    data["retry_count"] = preserved_retry
    write_json(path, data)


def _fill_budget(
    vault_dir: Path, budget_cap: float | None, max_cycles: int | None
) -> tuple[float, int]:
    """Backfill omitted budget arguments from the spec-061 ladder (issue #233)."""
    from ..cli._budget_resolve import fill_missing_run_budget

    return fill_missing_run_budget(vault_dir, budget_cap, max_cycles)


def _cycle_research_report_path(vault_dir: Path, cycle_num: int) -> Path:
    """Return the path to a cycle's research.json.

    Keep this in ONE place because the cycle runner writes the file
    with a zero-padded 3-digit index (``cycle-001-research.json``) while the
    orchestrator used to look it up with ``f"cycle-{cycle_num}"`` — the
    mismatch silently disabled coverage updates and budget logging for any
    multi-digit-free cycle number. One helper, one format, no drift.
    """
    return vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"


def _incremental_retry_after_cg_fail(
    vault_dir: Path,
    cycle_num: int,
    budget_cap: float,
    max_cycles: int,
    spec: SpecConfig | None,
    *,
    cycle_runner: Callable[[Path, int, float, int], int] | None = None,
) -> tuple[int, int, bool, str]:
    """Run one cycle with up to two CG-failure retries.

    Returns ``(returncode, retry_count, aborted, abort_reason)``.
    Accepted batches' notes are NEVER deleted between attempts (Q3).

    ``spec`` is reserved for future prompt/correction wiring (T056+).
    ``cycle_runner`` is injectable for unit tests so the retry control flow can
    be exercised without monkeypatching the module global (issue #86). When
    ``None`` (production), ``run_cycle_steps`` is resolved at call time. There
    is no longer a monkeypatch path to keep working: it is a guarded
    anti-pattern (``tests/_helpers/test_cycle_runner_seam_guard.py``).
    """
    _ = spec
    runner = cycle_runner or run_cycle_steps
    last_cg: GateResult | None = None
    for attempts in range(1, 4):
        returncode = runner(vault_dir, cycle_num, budget_cap, max_cycles)
        if returncode == 2:
            return (
                2,
                attempts - 1,
                True,
                "cycle_runner returned structural error",
            )
        if returncode == 1:
            # TERMINATE (issue #158): the cycle deliberately stopped before the
            # note-writing DFS — scout returned "no DFS this cycle" (Condition
            # A/B/C). Zero notes is BY DESIGN on this path, so the CG-001
            # min-cycle-yield gate must NOT fire and the cycle must NOT be
            # retried. Falling through re-ran the whole cycle (a fresh Step 0
            # vault_metrics + a multi-minute scout LLM call); on the rc7
            # reference-vault run the retry's Step 0 failed and aborted cycle 1 with
            # a spurious "cycle_runner returned structural error". A TERMINATE
            # is a terminal verdict, not a low-yield failure.
            return (1, attempts - 1, False, "")

        report_file = _cycle_research_report_path(vault_dir, cycle_num)
        research_report: dict = {}
        if report_file.exists():
            try:
                research_report = json.loads(report_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                research_report = {}

        cg_result = run_gate(
            CG001_min_cycle_yield,
            vault_dir,
            research_report,
            cycle_number=cycle_num,
            max_cycles=max_cycles,
        )
        if cg_result.status in ("PASS", "WARN"):
            return (returncode, attempts - 1, False, "")

        last_cg = cg_result
        if cg_result.status == "FAIL":
            try:
                build_directive(
                    vault_dir,
                    failing_gates=[cg_result],
                    cycle=cycle_num,
                    batch=None,
                )
            except Exception as exc:
                _LOG.warning(f"WARN: correction directive failed: {exc}")

    metric = last_cg.metric_value if last_cg is not None else 0
    return (
        2,
        2,
        True,
        f"CG-001 failed after 3 attempts; last metric: {metric}",
    )


def run_single_cycle(
    vault_dir: Path,
    cycle_num: int,
    budget_cap: float | None = None,
    max_cycles: int | None = None,
    spec: SpecConfig | None = None,
    resume: bool = False,
    target_topics: list[str] | None = None,
    *,
    cycle_runner: Callable[[Path, int, float, int], int] | None = None,
) -> int:
    """Run one research cycle via cycle_runner. Returns the exit code.

    When `resume=True` and `spec` is provided, the scout prompt is re-rendered
    with `target_topics` (unmet expected filenames from repo-scan.json) and
    `exclude_topics` (existing note filenames) so the scout focuses on gaps
    rather than rediscovering covered topics (feature 002, FR-015).

    ``budget_cap=None`` / ``max_cycles=None`` resolve through the spec-061
    ladder. They used to default to ``10.0`` / ``5`` — the fourth and fifth
    budget knobs the spec was written to eliminate, reachable only by omitting
    an argument (issue #233).

    ``cycle_runner`` is the injectable seam every caller that needs a stand-in
    runner uses, in place of monkeypatching the module global (issue #86).
    ``None`` (production) resolves ``run_cycle_steps`` at call time.
    """
    budget_cap, max_cycles = _fill_budget(vault_dir, budget_cap, max_cycles)
    pre_run_qr_retry = _snapshot_existing_cycle_quality_retry_count(
        vault_dir, cycle_num, resume=resume
    )

    if spec is not None:
        try:
            plan = research_plan.generate_plan(vault_dir, spec, cycle_num)
            (vault_dir / "_pipeline").mkdir(parents=True, exist_ok=True)
            (vault_dir / "_pipeline" / "research-plan.md").write_text(
                plan.to_markdown(), encoding="utf-8"
            )
            cycles_dir = vault_dir / "_pipeline" / "cycles"
            cycles_dir.mkdir(parents=True, exist_ok=True)
            (cycles_dir / f"cycle-{cycle_num:03d}-research-plan.md").write_text(
                plan.to_markdown(), encoding="utf-8"
            )
            plan_narrator.prepend_narrative(vault_dir, cycle_num)
        except Exception as exc:
            _LOG.info(
                f"WARN: plan generation/narration failed for cycle {cycle_num}: {exc}"
            )

        _reconcile_orphan_notes_at_cycle_start(vault_dir, cycle_num)

    # Resume-mode re-render AND cycle >= 2 per-cycle re-render. Feature
    # 003 (Phase 2): the scout prompt needs to pick up Phase 2 auto-
    # promoted proposals and persistent rejects from the previous
    # cycle, so we re-render whenever there's a previous cycle's worth
    # of state on disk. Cycle 1 still uses the generate-time prompt.
    if spec is not None and (resume or cycle_num >= 2):
        _render_cycle_scout_prompt(
            spec, vault_dir, cycle_num, target_topics=target_topics
        )

    returncode, retry_count, aborted, abort_reason = _incremental_retry_after_cg_fail(
        vault_dir, cycle_num, budget_cap, max_cycles, spec, cycle_runner=cycle_runner
    )

    cycles_dir = vault_dir / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        cycles_dir / f"cycle-{cycle_num:03d}-retry-state.json",
        {
            "retry_count": retry_count,
            "aborted": aborted,
            "abort_reason": abort_reason,
        },
        indent=None,
        trailing_newline=False,
    )

    # Spec 068 (FR2/FR3): recompute coverage from disk BEFORE the quality report
    # so the report's ``coverage_snapshot`` — the source the digest and
    # ``vault status`` read — reflects the notes this cycle actually wrote. The
    # snapshot previously lagged a cycle because the coverage update ran *after*
    # ``write_report``; on the rc7 vault that surfaced as ``0% → 0%`` despite
    # ~107 notes on disk. ``update_after_cycle`` is now a full disk recount with
    # a loud WARN-and-trust invariant (FR1/FR2).
    #
    # Recompute on BOTH CONTINUE (rc==0) and TERMINATE (rc==1) — the agent may
    # terminate after still writing notes this cycle, and those notes count
    # toward coverage + the auto-resume decision. ABORT (rc==2) is skipped
    # because the cycle report is unreliable then. Skip CG-aborted intermediate
    # attempts (017 Q3): they must not roll back coverage-targets / notes.
    cycle_report: dict | None = None
    if not aborted and returncode in (0, 1):
        report_file = _cycle_research_report_path(vault_dir, cycle_num)
        if report_file.exists():
            try:
                cycle_report = json.loads(report_file.read_text(encoding="utf-8"))
                update_after_cycle(vault_dir, cycle_report, cycle_number=cycle_num)
            except Exception as e:
                _LOG.warning(f"WARN: failed to update coverage from cycle report: {e}")

    quality_report.write_report(vault_dir, cycle_num)
    _restore_cycle_quality_retry_after_report(
        vault_dir,
        cycle_num,
        preserved_retry=pre_run_qr_retry,
        aborted=aborted,
        resume=resume,
    )

    if cycle_report is not None:
        try:
            _append_budget_log(vault_dir, cycle_num, cycle_report)
        except Exception as e:
            _LOG.warning(f"WARN: failed to append budget log: {e}")

    _quarantine_out_of_scope_notes(vault_dir, spec)
    _rebuild_indexes_best_effort(vault_dir)

    # Human-readable one-page summary of this cycle. Best-effort: the writer
    # never raises, so a malformed sidecar can't influence the cycle exit
    # code (the orchestrator has already decided that above).
    summary_path = _write_cycle_summary(
        vault_dir,
        cycle_num,
        exit_code=returncode,
        exit_reason=abort_reason if aborted else None,
    )
    _LOG.info(f"[cycle {cycle_num}] summary: {summary_path}")
    return returncode


def _aborted_marker(vault_dir: Path, cycle: int) -> Path:
    return vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-aborted.json"


def mark_cycle_aborted(vault_dir: Path, cycle: int, *, reason: str) -> None:
    """Record that ``cycle`` aborted, so ``--resume`` does not skip past it.

    Spec 070 F10. ``_highest_completed_cycle`` anchors resume on the highest
    ``cycle-NNN-quality-report.json`` and documents the assumption that "a cycle
    that aborts mid-stream never writes the report". That assumption is false —
    verified across five live vaults, where EVERY aborted (exit 2) cycle had
    written its report. The anchor therefore advanced past the aborted cycle and
    its work was never retried; one such cycle had written 11 notes and had all
    11 rejected.

    Best-effort: a marker we cannot write must never change the run's exit code.
    """
    from .atomic_write import write_json

    marker = _aborted_marker(vault_dir, cycle)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            marker,
            {
                "cycle": cycle,
                "reason": reason,
                "aborted_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
    except OSError as exc:  # pragma: no cover - advisory
        _LOG.warning("[orchestrator] could not write abort marker: %s", exc)


def clear_cycle_aborted(vault_dir: Path, cycle: int) -> None:
    """Drop ``cycle``'s abort marker after it completes cleanly (spec 070 F10)."""
    try:
        _aborted_marker(vault_dir, cycle).unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover - advisory
        _LOG.warning("[orchestrator] could not clear abort marker: %s", exc)


def is_archived(vault_dir: Path) -> bool:
    """True when ``settings.yaml::archived`` is set (spec 071).

    Reads the key directly rather than through ``load_vault_settings``. The
    typed loader validates the WHOLE file, so a vault with, say, no
    ``pipeline.max_cycles`` raises before ``archived`` is ever reached — and an
    archived vault is exactly the one whose pipeline config nobody has kept
    current. The real codebase-vault is in that state: settings predating spec
    061, where routing this through the typed loader made the flag silently
    inert. ``archived`` must hold under every circumstance, including a
    settings file that is otherwise invalid.

    Only a literal YAML ``true`` archives. A missing file, unreadable file,
    unparseable YAML or a typo all read as NOT archived — those are different
    failures, surfaced on their own terms; defaulting to "archived" would
    strand a working vault. The typed loader still rejects a non-boolean value
    outright (``_parse_archived``), so a typo is not silently tolerated
    wherever settings do load.
    """
    settings_path = vault_dir / "settings.yaml"
    try:
        import yaml

        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(raw, dict) and raw.get("archived") is True


def run_cycles(
    spec: SpecConfig,
    vault_dir: Path,
    start_cycle: int = 1,
    resume: bool = False,
    *,
    budget: BudgetResolution | None = None,
) -> int:
    """Run cycles until either successful completion or budget/cycle exhaustion.

    Loop semantics (constitution v1.3.0 § Principle II "Loop continuation is
    orchestrator-owned"):

    Each cycle, run scout + research + topic_harvest, then evaluate three
    continuation triggers — ANY of them → run another cycle (subject to
    budget_cap and max_cycles):

      1. Scout's `topics_found.new` is non-empty (new material discovered).
      2. The cycle's `cycle-NNN-harvest.json` lists unresolved followups
         (orphan wikilinks the research pass surfaced but didn't write).
      3. Any note in `data_vault/` matches the stub criteria (Principle
         VIII), OR vault_health.py reports orphan/stub body wikilinks.

    Exit conditions:

    - **Successful** (rc=0, Phase 3 finalizes): all three triggers clear
      AND coverage targets all met. The vault is declared complete.
    - **Source-exhausted** (rc=1): all three triggers clear but coverage
      is NOT met — scope/sources can't yield enough material. User must
      narrow targets or add sources.
    - **Constrained** (rc=1): budget cap or max_cycles tripped with at
      least one trigger still firing. Punch list of deferred items printed
      so user can `--resume`.
    - **Abort** (rc=2): structural error inside ``run_single_cycle`` (e.g.
      scout JSON malformed). Stops immediately.

    Auto-promotion of high-citation orphans into ``coverage-targets.json``
    is owned by ``scripts/topic_harvest.py`` (called as Step 7 of the
    cycle runner). By the time ``run_single_cycle`` returns, the
    coverage targets already reflect the latest emergent topology, so the
    orchestrator's ``all_targets_met`` check sees the dynamic-extension
    state without duplicating the logic. Threshold is configured via
    ``pipeline.backlog_promotion_threshold`` in the vault's ``settings.yaml``.
    """
    # Spec 061: the per-cycle budget is resolved from settings + CLI flags
    # (canonical pipeline.max_cycles / pipeline.budget_usd), NOT the baked spec.
    # The CLI passes an explicit ``budget``; a direct/test caller that omits it
    # gets the vault's settings-driven resolution. ``max_usd is None`` ⇒ uncapped
    # (budget_cap=0.0 disables the ``cumulative >= budget_cap > 0`` guard below).
    if budget is None:
        from ..cli._budget_resolve import resolve_cycle_budget_from_path

        budget = resolve_cycle_budget_from_path(vault_dir / "settings.yaml")
    budget_cap = budget.max_usd if budget.max_usd is not None else 0.0
    max_cycles = budget.max_cycles
    # Issue #239: `budget_cap` is a LIFETIME ceiling — it is compared against
    # every cycle the vault has ever run. `--max-usd-this-run` is the per-run
    # reading, and a per-run number needs a zero point: the vault's spend at
    # the instant this process takes over. Reading it BEFORE the loop (rather
    # than deriving it from `start_cycle`) is what makes a resume honest — a
    # cycle that already spent half its money before the pause has spent it,
    # and this run is not entitled to buy that work again inside its own
    # ceiling.
    run_baseline_usd = _cumulative_sidecar_cost(vault_dir, up_to=max(start_cycle, 1))

    # Spec 071: an archived vault is finished — refuse before ANY side effect.
    # This sits above `begin_run` deliberately: that opens a git branch and the
    # run report follows, and an archived vault must come away with neither.
    # The guard lives here rather than only in the CLI so every caller is
    # covered — a stale shim, a cron entry, a script, a test harness.
    if is_archived(vault_dir):
        _LOG.error(
            "[orchestrator] refusing to run: %s is archived. No research cycle "
            "may write to an archived vault. It stays fully queryable "
            "(`./vault ask`, `status`, `digest`, `re-grade`) and still takes "
            "framework upgrades (`./vault update`). To resume research, set "
            "`archived: false` in %s.",
            vault_dir,
            vault_dir / "settings.yaml",
        )
        return 2

    # Spec 050 / Principle X: open a research branch (or reuse on
    # ``--resume``). HARD STOP on dirty main — translate into exit 2 so
    # the user sees the operator-friendly message without a traceback.
    try:
        commit_ctx = vault_commit.begin_run(vault_dir, kind="research", resume=resume)
    except vault_commit.VaultCommitDirtyError as exc:
        _LOG.error("[orchestrator] auto-commit invariant blocked the run:\n%s", exc)
        _finalise_run_report(
            vault_dir,
            final_exit_code=2,
            final_exit_reason="vault_commit invariant: dirty main or stale branch",
        )
        return 2

    if resume:
        try:
            merge_expected_filenames_from_scan(vault_dir)
        except Exception as e:
            _LOG.warning(f"WARN: merge_expected_filenames_from_scan failed: {e}")

    def _commit_this_cycle(cycle_num: int, exit_reason: str | None = None) -> list[str]:
        """Auto-commit hook called once per ``run_single_cycle`` return.

        Best-effort: any failure WARNs but never alters the orchestrator's
        rc. The commit body uses whatever cycle artifacts already exist.
        Returns the list of paths left untracked under ``data_vault/`` after
        the commit (spec 062 FR2 — non-empty ⇒ caller forces a constrained exit).

        Issue #155: the verifier-rejected sweep MUST run BEFORE
        ``vault_commit.commit_cycle`` so the quarantine MOVE (delete from
        ``data_vault/`` + add under ``_pipeline/quarantine/``) lands in the
        cycle commit atomically. Without this, a constrained / aborted /
        externally-killed exit leaves the deletes uncommitted in the working
        tree (the rc7 reference-vault GA-003 failure mode).
        """
        # Pre-commit safety net: sweep verifier-rejected notes into quarantine
        # so the upcoming commit captures the move (both the data_vault/ DELETE
        # and the _pipeline/quarantine/ ADD) as one atomic cycle commit.
        try:
            _quarantine_rejected_notes(vault_dir)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("[orchestrator] pre-commit quarantine sweep raised: %s", exc)
        summary = _cycle_commit_summary(vault_dir, cycle_num)
        if exit_reason:
            summary["exit_reason"] = exit_reason
        try:
            result = vault_commit.commit_cycle(
                vault_dir, cycle=cycle_num, summary=summary, ctx=commit_ctx
            )
            return list(getattr(result, "untracked_paths", []) or [])
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("[orchestrator] vault_commit.commit_cycle raised: %s", exc)
            return []

    def _finalise(rc: int, reason: str) -> None:
        """Wraps run-report + auto-commit run-completion at every exit path."""
        # Spec 062 FR1 (+ issue #155): a rejected note must never be silently
        # shippable. The per-cycle ``_commit_this_cycle`` sweep handles the
        # common case (move ⇒ commit atomically). This final sweep is the
        # idempotent safety net for any rejection that landed between the last
        # cycle commit and the run finalisation (e.g. an aborted final cycle).
        # On the happy path this returns 0.
        rejected_unresolved = _quarantine_rejected_notes(vault_dir)
        _finalise_run_report(
            vault_dir,
            final_exit_code=rc,
            final_exit_reason=reason,
            cycle_budget_configured=budget.max_cycles,
            cycle_budget_source=budget.max_cycles_source,
            rejected_unresolved=rejected_unresolved,
        )
        # Spec 063 Q4: on a clean exit, record the acceptance scorecard. This is
        # a separate, recorded signal — it MUST NOT change the run's own exit
        # code (the harness verdict lives only in _pipeline/acceptance/).
        if rc == 0:
            _autorun_acceptance(vault_dir)
        try:
            vault_commit.complete_run(
                vault_dir, final_rc=rc, final_reason=reason, ctx=commit_ctx
            )
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("[orchestrator] vault_commit.complete_run raised: %s", exc)

    # Spec 070 F5: `max_cycles` is an ABSOLUTE ceiling, not "run N more cycles".
    # On a resume anchored past that ceiling the range below is empty, the loop
    # body never runs, and control falls through to `_constrained_exit` — which
    # narrates entirely at INFO and is therefore invisible under the non-TTY
    # WARNING default. Exit code and control flow are unchanged; this is the
    # diagnostic that was missing.
    if start_cycle > max_cycles:
        _LOG.error(
            "[orchestrator] nothing to do — resume is anchored at cycle %d but the "
            "cycle ceiling is %d (from %s). `max_cycles` is an ABSOLUTE ceiling, "
            "not a count of additional cycles, and cycle %d has already completed. "
            "Raise the ceiling above %d (`--max-cycles %d`, or `pipeline.max_cycles` "
            "in the vault's settings.yaml) to run another cycle.",
            start_cycle,
            max_cycles,
            budget.max_cycles_source,
            start_cycle - 1,
            start_cycle - 1,
            start_cycle,
        )

    for cycle in range(start_cycle, max_cycles + 1):
        _LOG.info(f"[orchestrator] starting cycle {cycle}/{max_cycles}")
        try:
            rc = run_single_cycle(
                vault_dir, cycle, budget_cap, max_cycles, spec=spec, resume=resume
            )
        except BaseException as exc:
            # Ctrl-C, a budget or approval pause (``SystemExit``) and a crash
            # all leave through the cycle runner's guard, which writes the
            # quality report and clears ``in_progress_cycle`` on EVERY exit.
            # Unmarked, the cycle then reads as completed: `--resume` anchors
            # one past it, never returns to it, and re-checks a standing
            # ``BUDGET_PAUSED`` against a cycle that spent nothing. Same
            # marker as the rc=2 return below (spec 070 F10), same remedy.
            mark_cycle_aborted(
                vault_dir,
                cycle,
                reason=f"cycle {cycle} interrupted ({type(exc).__name__})",
            )
            raise
        if rc == 2:
            _LOG.info(f"[orchestrator] cycle {cycle} aborted (exit 2)")
            # Spec 070 F10: the cycle wrote a quality report on its way out, so
            # without this marker `--resume` would anchor PAST it and its work
            # would never be retried.
            mark_cycle_aborted(
                vault_dir, cycle, reason=f"cycle {cycle} aborted (exit 2)"
            )
            _commit_this_cycle(cycle, exit_reason="aborted")
            _finalise(2, f"cycle {cycle} aborted (exit 2)")
            return 2
        clear_cycle_aborted(vault_dir, cycle)
        untracked = _commit_this_cycle(cycle)
        if untracked:
            # Spec 062 FR2 / Principle X: content left untracked under
            # data_vault/ after the cycle commit is a fail-loud, constrained
            # exit — never silently shippable.
            reason = (
                f"untracked data_vault/ content after cycle {cycle} commit "
                f"({len(untracked)} path(s)); auto-commit invariant violated"
            )
            _LOG.error("[orchestrator] %s", reason)
            _finalise(1, reason)
            return 1

        # Evaluate the three continuation triggers. Auto-promotion has
        # already happened inside the cycle runner's Step 7 (topic_harvest),
        # so all_targets_met() reflects any newly-extended coverage.
        new_topics = _scout_new_topics(vault_dir, cycle)
        followups = _harvest_followups(vault_dir, cycle)
        stubs = scan_stubs(vault_dir, spec)
        health_issues = _run_health_gate(vault_dir)
        coverage_met = all_targets_met(vault_dir)

        has_fuel = bool(new_topics or followups or stubs or health_issues)

        # Successful exit: no fuel + coverage met → Phase 3.
        if not has_fuel and coverage_met:
            _LOG.info(
                "[orchestrator] vault complete — coverage met, no stubs, "
                "no orphans, scout returned no new topics."
            )
            _finalise(0, "vault complete — coverage met, no fuel")
            return 0

        # Source-exhausted exit: no fuel but coverage unmet → tell user.
        if not has_fuel and not coverage_met:
            unmet = unmet_targets(vault_dir)
            # Issue #242: rc=1, so FR6 applies — the headline is the exit
            # reason (ERROR), the categories and the remedy are what makes it
            # actionable (WARNING). At INFO none of it survived the non-TTY
            # default and the run just stopped.
            _LOG.error(
                f"[orchestrator] research loop has no remaining fuel "
                f"(scout found 0 new topics, backlog empty, no stubs/orphans) "
                f"but {len(unmet)} coverage target(s) remain unmet:"
            )
            for cat in unmet:
                _LOG.warning(f"  - {cat}")
            _LOG.warning(
                "[orchestrator] sources cannot yield the declared targets. "
                "Either narrow `coverage_targets`/`scope.include` in the spec, "
                "or add more `data_sources`, then re-run."
            )
            _finalise(1, f"source-exhausted: {len(unmet)} coverage target(s) unmet")
            return 1

        # Cumulative-cost cap. Sums sidecar totals across every cycle so
        # far — a LIFETIME ceiling, which is what `--max-usd` has always been
        # (issue #239). When this trips, exit constrained even if
        # cycle < max_cycles.
        cumulative = _cumulative_sidecar_cost(vault_dir, up_to=cycle)

        # Per-run ceiling (`--max-usd-this-run`). Measured from the baseline
        # taken before the first cycle, so history the operator already paid
        # for cannot consume the budget they just authorised. Checked first
        # because it is the tighter, more recently stated intent.
        run_cap = budget.max_usd_this_run
        if run_cap is not None and run_cap > 0:
            this_run = cumulative - run_baseline_usd
            if this_run >= run_cap:
                reason = (
                    f"run budget reached (${this_run:.4f} spent this run "
                    f"≥ ${run_cap:.2f}; ${cumulative:.4f} lifetime)"
                )
                rc_run = _constrained_exit(
                    vault_dir,
                    reason=reason,
                    new_topics=new_topics,
                    followups=followups,
                    stubs_count=len(stubs),
                    health_count=len(health_issues),
                    coverage_met=coverage_met,
                )
                _finalise(rc_run, reason)
                return rc_run

        if cumulative >= budget_cap > 0:
            rc_constrained = _constrained_exit(
                vault_dir,
                reason=f"budget cap reached (${cumulative:.4f} ≥ ${budget_cap:.2f})",
                new_topics=new_topics,
                followups=followups,
                stubs_count=len(stubs),
                health_count=len(health_issues),
                coverage_met=coverage_met,
            )
            _finalise(
                rc_constrained,
                f"budget cap reached (${cumulative:.4f} ≥ ${budget_cap:.2f})",
            )
            return rc_constrained

        # Otherwise: fuel exists, room to keep going. Re-arm resume mode so
        # the next cycle's scout prompt is rendered against the up-to-date
        # vault state.
        resume = True
        try:
            merge_expected_filenames_from_scan(vault_dir)
        except Exception as e:
            _LOG.info(
                f"WARN: merge_expected_filenames_from_scan failed on auto-resume: {e}"
            )

    # Fell through max_cycles with fuel still firing → constrained exit.
    rc_final = _constrained_exit(
        vault_dir,
        reason=f"max_cycles ({max_cycles}) reached",
        new_topics=_scout_new_topics(vault_dir, max_cycles),
        followups=_harvest_followups(vault_dir, max_cycles),
        stubs_count=len(scan_stubs(vault_dir, spec)),
        health_count=len(_run_health_gate(vault_dir)),
        coverage_met=all_targets_met(vault_dir),
    )
    _finalise(rc_final, f"max_cycles ({max_cycles}) reached")
    return rc_final


def _finalise_run_report(
    vault_dir: Path,
    *,
    final_exit_code: int,
    final_exit_reason: str,
    cycle_budget_configured: int | None = None,
    cycle_budget_source: str | None = None,
    rejected_unresolved: int | None = None,
) -> None:
    """Write the end-of-pipeline run report at every orchestrator exit.

    Never raises (the writer is already best-effort) and never alters the
    exit code — the caller already decided that. Echoes the report path so
    the operator sees it in the run log. ``cycle_budget_*`` carry the spec-061
    provenance (configured value + where it came from) for the run report's
    ``cycle_budget`` block (FR4 / spec 063 GA-004). ``rejected_unresolved``
    carries the spec-062 FR1 quarantine count (the signal spec 063 GA-001
    consumes).
    """
    try:
        path = _write_run_report(
            vault_dir,
            final_exit_code=final_exit_code,
            final_exit_reason=final_exit_reason,
            cycle_budget_configured=cycle_budget_configured,
            cycle_budget_source=cycle_budget_source,
            rejected_unresolved=rejected_unresolved,
        )
        _LOG.info(f"[orchestrator] run report: {path}")
    except Exception as exc:
        _LOG.warning(f"[orchestrator] WARN: run_report failed: {exc}")


def _autorun_acceptance(vault_dir: Path) -> None:
    """Record the acceptance scorecard at a clean exit (spec 063 Q4).

    Best-effort and silent: writes ``_pipeline/acceptance/report-<date>.{json,md}``
    but never prints to stdout and never raises — the acceptance verdict is a
    separate recorded signal and MUST NOT change the run's own exit code.
    """
    try:
        from ..cli.acceptance import build_scorecard, write_scorecard

        scorecard = build_scorecard(vault_dir)
        json_path, _md = write_scorecard(vault_dir, scorecard)
        _LOG.info(
            "[orchestrator] acceptance scorecard: %s (overall %s)",
            json_path,
            scorecard["overall"]["status"],
        )
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("[orchestrator] WARN: acceptance auto-run failed: %s", exc)


def _cycle_commit_summary(vault_dir: Path, cycle_num: int) -> dict[str, object]:
    """Best-effort cycle summary for the auto-commit body (spec 050).

    Pulls counts and gate verdicts from artifacts the cycle already
    writes: the quality-report (note counts + gate verdict) and the
    cycle-summary markdown header (wall time, cost). Returns a partial
    dict; ``vault_commit._format_cycle_body`` renders gracefully when
    fields are missing.
    """
    summary: dict[str, object] = {}
    qr_path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_num:03d}-quality-report.json"
    )
    if qr_path.is_file():
        try:
            qr = json.loads(qr_path.read_text(encoding="utf-8"))
            notes = qr.get("notes") or {}
            summary["notes_added"] = notes.get("created")
            summary["notes_updated"] = notes.get("updated")
            summary["notes_archived"] = notes.get("archived")
            verdict = qr.get("overall_verdict") or qr.get("verdict")
            if verdict:
                summary["gate_verdict"] = verdict
        except Exception:  # pragma: no cover - defensive
            pass
    research_path = _cycle_research_report_path(vault_dir, cycle_num)
    if research_path.is_file():
        try:
            rr = json.loads(research_path.read_text(encoding="utf-8"))
            usd = rr.get("cost_usd") or rr.get("total_cost_usd")
            if usd is not None:
                summary["cost_usd"] = usd
        except Exception:  # pragma: no cover - defensive
            pass
    return summary


def _scout_new_topics(vault_dir: Path, cycle_num: int) -> list[str]:
    """Return the scout's `topics_found.new` list for ``cycle_num``, or [] if
    the scout JSON is missing / malformed. Used as one of the three
    continuation triggers (constitution v1.3.0 § Principle II)."""
    scout_path = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-scout.json"
    )
    if not scout_path.is_file():
        return []
    try:
        data = json.loads(scout_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    found = data.get("topics_found")
    if isinstance(found, dict):
        new = found.get("new") or []
        if isinstance(new, list):
            return [str(t) for t in new]
    return []


def _harvest_followups(vault_dir: Path, cycle_num: int) -> list[dict]:
    """Return the cycle's harvest followups (orphan wikilinks not yet
    written), or [] if the harvest manifest is absent. Each entry is a
    dict with at least ``title`` and ``citation_count`` keys, per
    ``scripts/topic_harvest.py``'s contract."""
    harvest_path = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-harvest.json"
    )
    if not harvest_path.is_file():
        return []
    try:
        data = json.loads(harvest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    followups = data.get("followups") or []
    if isinstance(followups, list):
        return [f for f in followups if isinstance(f, dict)]
    return []


def _constrained_exit(
    vault_dir: Path,
    *,
    reason: str,
    new_topics: list,
    followups: list[dict],
    stubs_count: int,
    health_count: int,
    coverage_met: bool,
) -> int:
    """Print a punch list of deferred work and return rc=1.

    The user can `--resume` later to keep working through the fuel. This
    is the constitution-defined "constrained exit" — the run is incomplete
    but the system has captured everything needed to pick up where it
    left off.

    Issue #242: this whole narration used to be ``INFO``, and ``_log_level``
    FR-005 drops the level to ``WARNING`` whenever stdout is not a TTY — so a
    cron/launchd run got rc=1 and nothing else. The reason is the *exit
    reason of a non-zero exit*, which is what ``ERROR`` is for and what the
    ``cli.main`` backstop counts; the punch list is the operator's remedy and
    is useless without it, so it rides at ``WARNING``.
    """
    _LOG.error(f"[orchestrator] constrained exit — {reason}")
    _LOG.warning("[orchestrator] deferred work:")
    if new_topics:
        _LOG.warning(
            f"  - {len(new_topics)} new topic(s) the latest scout flagged "
            "but the cycle ran out of budget/cycles to research"
        )
    if followups:
        _LOG.warning(
            f"  - {len(followups)} orphan wikilink(s) in the backlog "
            "(see _pipeline/research-backlog.md)"
        )
    if stubs_count:
        _LOG.warning(f"  - {stubs_count} stub note(s) (see Principle VIII criteria)")
    if health_count:
        _LOG.warning(
            f"  - {health_count} unresolved body wikilink(s) "
            "(run `python scripts/vault_health.py <vault>` for the list)"
        )
    if not coverage_met:
        unmet = unmet_targets(vault_dir)
        _LOG.warning(f"  - {len(unmet)} coverage category/categories unmet:")
        for cat in unmet:
            _LOG.warning(f"      · {cat}")
    _LOG.warning(
        "[orchestrator] raise `pipeline.max_cycles` (or `pipeline.budget_usd`) "
        "in the vault's settings.yaml — or pass `--max-cycles N` — and re-run "
        "`research-framework generate --resume` to keep going."
    )
    return 1


def _cycle_made_progress(vault_dir: Path, cycle_num: int) -> bool:
    """Return True if cycle ``cycle_num``'s research report shows any
    note created or updated. Used to decide whether auto-resume is
    worth trying — if the agent terminated without adding anything,
    another cycle at the same inputs would loop forever.
    """
    report_file = _cycle_research_report_path(vault_dir, cycle_num)
    if not report_file.exists():
        return False
    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    created = report.get("notes_created") or []
    updated = report.get("notes_updated") or []
    return bool(created) or bool(updated)


def _run_health_gate(vault_dir: Path) -> list[str]:
    """Invoke ``scripts/vault_health.py`` in offline mode and return a list
    of human-readable issue descriptions (empty == clean).

    Health check runs in a subprocess-free way (direct import from the
    installed or bundled scripts dir) to keep startup fast and avoid
    re-entering shell argument parsing.
    """
    scripts_dir = vault_dir / "scripts"
    if not (scripts_dir / "vault_health.py").exists():
        return []

    import importlib.util
    import sys as _sys

    spec_mod = importlib.util.spec_from_file_location(
        "vault_health_gate", scripts_dir / "vault_health.py"
    )
    if spec_mod is None or spec_mod.loader is None:
        return []
    module = importlib.util.module_from_spec(spec_mod)
    _sys.modules.setdefault("vault_health_gate", module)
    try:
        spec_mod.loader.exec_module(module)
    except Exception as e:
        return [f"vault_health.py failed to load: {e}"]

    try:
        report = module.run(vault_dir, apply=False, offline=True)
    except Exception as e:
        return [f"vault_health.py raised: {e}"]

    issues: list[str] = []
    for w in report.wikilinks:
        if w.classification in ("orphan", "stub"):
            issues.append(w.describe(vault_dir))
    for path, ntype, have, want in report.template_versions:
        try:
            rel = path.relative_to(vault_dir)
        except ValueError:
            rel = path
        issues.append(
            f"OUTDATED-TEMPLATE {rel} (type={ntype}, note={have or '(missing)'}, template={want})"
        )
    return issues


def _phase2_promoted_titles(vault_dir: Path, *, before_cycle: int) -> list[str]:
    """Return accepted-proposal titles from the most recent cycle's
    ``cycle-NNN-propose.json`` older than ``before_cycle``.

    Phase 2 auto-promote default: proposals from cycle N feed the scout's
    ``target_topics`` on cycle N+1. Only the *most recent* manifest is
    consulted — older cycles' proposals should have either become notes or
    fallen off; re-injecting them forever would drown the scout.

    Best-effort: any I/O / JSON failure returns an empty list so the
    cycle loop never dies on stale state.
    """
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        return []
    candidates: list[int] = []
    for p in cycles_dir.glob("cycle-*-propose.json"):
        stem = p.stem  # e.g. "cycle-003-propose"
        try:
            n = int(stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        if n < before_cycle:
            candidates.append(n)
    if not candidates:
        return []
    for n in sorted(candidates, reverse=True):
        path = cycles_dir / f"cycle-{n:03d}-propose.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        titles: list[str] = []
        for p in data.get("proposals") or []:
            if not isinstance(p, dict):
                continue
            t = p.get("title")
            if isinstance(t, str) and t.strip():
                titles.append(t.strip())
        return titles
    return []


def _persistent_reject_titles(vault_dir: Path) -> list[str]:
    """Read ``_pipeline/propose-rejects.md`` and return titles to exclude.

    Format written by ``scripts/topic_propose.py`` is::

        - **<title>** — cycle NNN (YYYY-MM-DD): <reason>

    We parse the bolded title from each bullet. Unknown lines are
    silently skipped (the file is human-editable — users may add
    comments or custom annotations).
    """
    import re as _re

    path = vault_dir / "_pipeline" / "propose-rejects.md"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _re.match(r"^\s*-\s+\*\*([^*\n]+?)\*\*", line)
        if m:
            title = m.group(1).strip()
            if title:
                out.append(title)
    return out


def _render_cycle_scout_prompt(
    spec: SpecConfig,
    vault_dir: Path,
    cycle_num: int,
    target_topics: list[str] | None = None,
) -> None:
    """Re-render the scout prompt for ``cycle_num`` with the current
    target/exclude lists, merging Phase 2 auto-promoted proposals into
    ``target_topics`` and persistent rejects into ``exclude_topics``.

    When ``target_topics`` is supplied (e.g. from ``--target-topics`` CLI),
    those entries are prepended before the coverage-gap and proposal lists.

    Lazy import to avoid a hard coupling between pipeline and generator
    modules at import time (they're sibling packages; keeps the dependency
    graph clean).
    """
    from ..generator.templates import render_scout_prompt
    from .source_manager import merge_into_prompt_context

    try:
        missing = unmet_expected_filenames(vault_dir)
    except Exception:
        missing = {}
    computed_topics: list[str] = list(target_topics or [])
    seen = {t.casefold() for t in computed_topics}

    for _, filenames in missing.items():
        for fn in filenames:
            if fn.casefold() not in seen:
                computed_topics.append(fn)
                seen.add(fn.casefold())

    # Phase 2 auto-promote: accepted proposals from cycle N-1 become
    # explicit target topics for cycle N. Dedup against what's already
    # in computed_topics (coverage may have already surfaced the same
    # filename).
    for t in _phase2_promoted_titles(vault_dir, before_cycle=cycle_num):
        if t.casefold() not in seen:
            computed_topics.append(t)
            seen.add(t.casefold())

    existing = set(existing_vault_filenames(vault_dir))
    existing.update(_persistent_reject_titles(vault_dir))

    # Enrich spec sources with active discovered sources from sources.db.
    # Falls back to spec.data_sources unchanged when sources.db doesn't exist.
    enriched_sources = merge_into_prompt_context(spec, vault_dir)
    enriched_spec = spec
    if enriched_sources is not spec.data_sources:
        # Shallow-copy the spec and swap in the enriched list so the render
        # function sees the discovered sources without mutating the original.
        import copy as _copy

        enriched_spec = _copy.copy(spec)
        enriched_spec.data_sources = enriched_sources

    try:
        render_scout_prompt(
            enriched_spec,
            vault_dir,
            target_topics=computed_topics,
            exclude_topics=sorted(existing),
        )
    except Exception as e:
        # Render failure is non-fatal — fall back to the generate-time prompt.
        _LOG.warning(f"WARN: cycle {cycle_num} scout-prompt re-render failed: {e}")


def _sum_sidecar_costs(vault_dir: Path, cycle_num: int) -> float | None:
    """Sum ``cost_usd`` from sidecar v1.1 files under ``agent-calls/`` (spec 028).

    Includes per-call, suffixed, and per-batch sidecars. Legacy flat
    ``cycle-{N}-*.cost.json`` paths are not read.

    FR-012: ``_quality_report_guard`` retries produce suffixed sidecars via
    ``dispatch()``'s filesystem allocator — this function sums them without
    special-casing retries.
    """
    agent_calls = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}" / "agent-calls"
    )
    if not agent_calls.is_dir():
        return None
    sidecars = sorted(agent_calls.glob("*.json"))
    if not sidecars:
        return None
    total = 0.0
    for path in sidecars:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            _LOG.warning(f"WARN: cost sidecar {path} unreadable: {e}")
            continue
        total += float(data.get("cost_usd") or 0.0)
    return total


def _append_budget_log(vault_dir: Path, cycle_num: int, report: dict) -> None:
    """Append one row per cycle to `_pipeline/budget-log.md`.

    Feature 002 (FR-016): budget-log accumulates across resume runs. Never
    overwrites — each `research-framework generate --resume` invocation adds rows.

    Cost source precedence (highest first):

    1. ``*.cost.json`` sidecars written by ``agent_call.py`` from the
       runtime's machine-readable output (``claude --output-format
       stream-json``). Authoritative when present.
    2. ``report.cost_estimate_usd`` / ``cumulative_cost_usd`` —
       agent-self-reported. Often 0 because skills don't know their
       own cost; kept as a fallback for vaults where the sidecar
       pipeline hasn't run.
    3. ``report.budget_consumed_usd`` — v2 schema alias, same caveats.
    """
    log_path = vault_dir / BUDGET_LOG_REL
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists() or log_path.stat().st_size == 0:
        log_path.write_text(
            "# Budget Log\n\n"
            "One row per completed cycle. Appends across `--resume` runs.\n\n"
            "| Timestamp | Cycle | Notes Created | Cycle Cost USD | Cumulative USD |\n"
            "|-----------|-------|---------------|----------------|----------------|\n",
            encoding="utf-8",
        )

    sidecar_cost = _sum_sidecar_costs(vault_dir, cycle_num)
    if sidecar_cost is not None:
        cycle_cost = sidecar_cost
        # Cumulative is the sum of every prior cycle's sidecar total
        # plus this cycle. We re-walk on every append rather than
        # storing a running tally because resume runs can interleave
        # cycles from earlier sessions.
        cumulative = _cumulative_sidecar_cost(vault_dir, up_to=cycle_num)
    else:
        # v2 and v1 reports use different field names — accept both.
        cycle_cost = float(
            report.get("cost_estimate_usd", report.get("budget_consumed_usd", 0)) or 0
        )
        cumulative = float(
            report.get("cumulative_cost_usd", report.get("budget_consumed_usd", 0)) or 0
        )
    notes_count = len(report.get("notes_created") or [])
    ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"| {ts} | {cycle_num} | {notes_count} | {cycle_cost:.4f} | {cumulative:.4f} |\n"
        )


def _cumulative_sidecar_cost(vault_dir: Path, *, up_to: int) -> float:
    """Sum every sidecar cost for cycles ``1..up_to`` (inclusive)."""
    total = 0.0
    for cycle in range(1, up_to + 1):
        cycle_total = _sum_sidecar_costs(vault_dir, cycle)
        if cycle_total is not None:
            total += cycle_total
    return total
