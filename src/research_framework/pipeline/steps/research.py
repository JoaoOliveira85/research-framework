"""Research step (spec 025 US6 B3)."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from .._helpers import cosmetic_correction as cc
from .._helpers import scout_correction as sc
from .._helpers import script_runner as sr
from .._helpers import source_signals as ss
from .._helpers import state as st
from ..atomic_write import write_json as _atomic_write_json
from ..gates import GateResult, run_gate
from ..gates_step import SG004_validate_vault_wrapper, SG005_frontmatter_completeness
from ._types import CycleContext, ResearchResult, ScoutResult, VerifierRejection

_LOG = logging.getLogger(__name__)


def _phase(ctx: CycleContext) -> int:
    __exit = 0
    vault_dir = ctx.vault_dir
    cycle_num = ctx.cycle_num
    cycle_3 = f"{cycle_num:03d}"
    scripts_dir = ctx.scripts_dir
    cycles_dir = ctx.cycles_dir
    prompts_dir = ctx.prompts_dir
    pipeline_dir = ctx.pipeline_dir or (vault_dir / "_pipeline")
    python_bin = ctx.python_bin
    env = dict(ctx.env)
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    research_report = cycles_dir / f"cycle-{cycle_3}-research.json"
    cycles_dir / f"cycle-{cycle_3}-pre-metrics.json"
    cycles_dir / f"cycle-{cycle_3}-post-metrics.json"
    assert scripts_dir is not None and cycles_dir is not None
    assert prompts_dir is not None and python_bin

    # --- Step 3: research (DFS) — batched note-writer (T056, T059, T074) ---

    dfs_prompt_src = prompts_dir / "dfs-prompt.md"
    if not dfs_prompt_src.exists():
        _LOG.error(f"ERROR: dfs prompt missing at {dfs_prompt_src}")
        return 2
    plan_md = pipeline_dir / "research-plan.md"
    if not plan_md.is_file():
        dfs_prompt_rendered = cycles_dir / f"cycle-{cycle_3}-dfs-prompt.rendered.md"
        sc._render_prompt(
            dfs_prompt_src,
            dfs_prompt_rendered,
            {
                "{CYCLE_NUM}": str(cycle_num),
                "{SCOUT_REPORT}": str(scout_report),
                "{RESEARCH_REPORT}": str(research_report),
            },
            vault_dir=vault_dir,
            cycle_num=cycle_num,
        )
        try:
            sr._run_script(
                python_bin,
                scripts_dir / "agent_call.py",
                "--vault",
                vault_dir,
                "--stage",
                "note_writer",
                "--prompt-file",
                dfs_prompt_rendered,
                "--cost-sidecar",
                cycles_dir
                / f"cycle-{cycle_3}"
                / "agent-calls"
                / "note_writer-batch-1.json",
                env=env,
                log_file=cycles_dir / f"cycle-{cycle_3}-research.log",
            )
        except sr._StepError:
            return 2
    else:
        from ..batch import (
            BatchResult,
            check_pace_at_midpoint,
            slice_topics_into_batches,
        )
        from ..research_plan import ResearchPlan

        try:
            raw_plan = plan_md.read_text(encoding="utf-8")
            plan = ResearchPlan.from_markdown(raw_plan)
            parsed_topics = sc._parse_priority_queue_from_plan_md(raw_plan)
            plan = dataclasses.replace(plan, priority_queue=parsed_topics)
        except Exception as exc:
            _LOG.error(f"ERROR: could not load research plan: {exc}")
            return 2
        eff_bs = ss._effective_note_writer_batch_size(vault_dir, plan)
        assignments = slice_topics_into_batches(plan, eff_bs)
        max_batches_cfg = ss._max_batches_per_cycle(vault_dir)
        data_vault = vault_dir / "data_vault"
        data_vault.mkdir(parents=True, exist_ok=True)

        correction_text = ""
        bundled_history: list[tuple[object, BatchResult]] = []
        cumulative_notes = 0
        note_writer_invocations = 0
        cycle_quota = max(1, int(plan.cycle_quota))
        n_batches_total = len(assignments)
        cap_tripped = False

        for i, assignment in enumerate(assignments):
            runtime_state = ctx.runtime_state
            if runtime_state is not None and runtime_state.should_abort:
                _LOG.warning(
                    "[cycle_runner] aborting note-writer loop — required-source "
                    "degradation threshold tripped"
                )
                return 2
            if cumulative_notes >= cycle_quota:
                break
            if note_writer_invocations >= max_batches_cfg:
                cap_tripped = True
                if runtime_state is not None:
                    runtime_state.note_writer_cap_tripped = True
                _LOG.warning(
                    "[cycle_runner] note-writer cap reached "
                    "(pipeline.max_batches_per_cycle=%s) — continuing cycle",
                    max_batches_cfg,
                )
                break

            incoming_gate_correction = correction_text
            if i > 0:
                pace_ph = st._empty_batch_result_for_pace(
                    cycle_num, assignment.batch_number
                )
                pace_dir = check_pace_at_midpoint(
                    plan,
                    bundled_history + [(assignment, pace_ph)],
                    assignment.batch_number,
                )
                if pace_dir is not None:
                    correction_text = (
                        correction_text + "\n\n" + pace_dir.to_prompt_block()
                    ).strip()

            prompt_correction = correction_text
            batch_rendered = (
                cycles_dir
                / f"cycle-{cycle_3}-batch-{assignment.batch_number:03d}-dfs.md"
            )
            sc._render_batch_note_writer_prompt(
                dfs_prompt_src=dfs_prompt_src,
                dest=batch_rendered,
                cycle_num=cycle_num,
                scout_report=scout_report,
                research_report=research_report,
                batch_topics=assignment.topics,
                correction_directive=prompt_correction,
            )

            seen_before: set[str] = set()
            if data_vault.is_dir():
                for p in data_vault.rglob("*.md"):
                    try:
                        rel = p.relative_to(data_vault)
                    except ValueError:
                        continue
                    if rel.name in ("_index.md", "_concepts.md", "_graph.md"):
                        continue
                    if "_templates" in rel.parts:
                        continue
                    seen_before.add(rel.as_posix())
                    seen_before.add(rel.name)

            # Snapshot body hashes for the anti-fraud detector. Only used on
            # correction batches (``incoming_gate_correction`` is non-empty),
            # so the normal happy path pays only the directory walk we were
            # already doing one block above.
            is_correction_batch = bool(incoming_gate_correction.strip())
            body_snapshot_before = (
                cc._snapshot_note_bodies(data_vault) if is_correction_batch else {}
            )

            ts0 = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                sr._run_script(
                    python_bin,
                    scripts_dir / "agent_call.py",
                    "--vault",
                    vault_dir,
                    "--stage",
                    "note_writer",
                    "--prompt-file",
                    batch_rendered,
                    "--cost-sidecar",
                    cycles_dir
                    / f"cycle-{cycle_3}"
                    / "agent-calls"
                    / f"note_writer-batch-{assignment.batch_number}.json",
                    "--batch-index",
                    str(assignment.batch_number),
                    "--topic-count",
                    str(len(assignment.topics)),
                    env=env,
                    log_file=cycles_dir / f"cycle-{cycle_3}-research.log",
                )
            except sr._StepError:
                return 2
            note_writer_invocations += 1
            skipped = st._read_skipped_topics_from_research(research_report)
            new_paths = st._discover_new_markdown_files(data_vault, seen_before)
            note_paths = sorted(new_paths, key=lambda p: p.as_posix())
            note_names = [p.relative_to(vault_dir).as_posix() for p in note_paths]
            if note_names:
                st._merge_research_notes(research_report, note_names)
            # B.2 (post-mortem 2026-05-30): backfill the framework-owned
            # `lifecycle.created_at_cycle` field so orchestrator's
            # "what did this cycle produce?" queries work. Idempotent;
            # see ``_stamp_lifecycle_cycle`` docstring for rationale.
            st._stamp_lifecycle_cycle(note_paths, int(cycle_3))

            sg4 = run_gate(SG004_validate_vault_wrapper, vault_dir)
            sg5 = run_gate(SG005_frontmatter_completeness, note_paths)
            sg_results: list[GateResult] = [sg4, sg5]
            syn = cc._synthetic_mid_batch_empty_sg005(
                assignment.batch_number,
                n_batches_total,
                note_paths,
                len(assignment.topics),
            )
            if syn is not None:
                sg_results.append(syn)
            if is_correction_batch:
                fraud = cc._detect_cosmetic_only_correction(
                    data_vault, body_snapshot_before, note_paths
                )
                if fraud is not None:
                    sg_results.append(fraud)

            ts1 = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            batch_result = BatchResult(
                cycle_number=cycle_num,
                batch_number=assignment.batch_number,
                started_at=ts0,
                finished_at=ts1,
                notes_written=note_names,
                skipped_topics=skipped,
                sg_gate_results=sg_results,
                topics=assignment.topics,
                correction_directive_in=incoming_gate_correction,
            )
            bout = (
                cycles_dir / f"cycle-{cycle_3}-batch-{assignment.batch_number:03d}.json"
            )
            _atomic_write_json(
                bout,
                batch_result.to_dict(),
            )
            bundled_history.append((assignment, batch_result))

            cumulative_notes += len(note_names)
            if batch_result.accepted:
                correction_text = ""
            else:
                failing = [g for g in sg_results if g.status == "FAIL"]
                if failing:
                    correction_text = sc._correction_prompt_text(
                        vault_dir,
                        failing,
                        cycle=cycle_num,
                        batch=assignment.batch_number,
                    )

        research_report.parent.mkdir(parents=True, exist_ok=True)
        if not research_report.is_file():
            _atomic_write_json(
                research_report,
                {"notes_created": [], "notes_updated": []},
            )
        try:
            rep_doc = json.loads(research_report.read_text(encoding="utf-8"))
            rep_doc["note_writer_cap_tripped"] = bool(cap_tripped)
            _atomic_write_json(research_report, rep_doc)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    # --- Step 3b: verifier (per-note quality check; best-effort) ---
    try:
        import yaml as _yaml

        from ..verifier import run_verifier_stage

        # Load settings from vault
        settings_path = vault_dir / "settings.yaml"
        _settings: dict = {}
        if settings_path.exists():
            try:
                _settings = (
                    _yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
                )
            except Exception:
                pass
        # Read research report
        if research_report.exists():
            _report = json.loads(research_report.read_text(encoding="utf-8"))
            run_verifier_stage(
                vault_dir,
                cycle_num,
                _report,
                scripts_dir=scripts_dir,
                settings=_settings,
            )
        else:
            _LOG.warning(
                "research report not yet available for verifier — skipping step 3b"
            )
    except Exception as e:
        _LOG.warning(f"WARN: verifier stage failed: {e} — continuing")

    # --- Step 3c: auto-normalize case-mismatched wikilinks (0.2.31) ---
    # The note-writer agent emits natural-language wikilinks
    # ([[Cassandra]], [[OMS]]) but filenames are lowercase-snake. Left
    # unfixed, the user's 0.2.30 audit found 207 broken links \u2014 the
    # vault graph fragmented across case-variants. The normalizer
    # (`auto_fix_moved_wikilinks`) only rewrites case mismatches where a
    # lowercase target already exists and never creates or deletes notes.
    # The spec-062 FR3 acronym pass (`resolve_acronym_links`) below MAY
    # additionally create deterministic alias/redirect stub notes, but it
    # likewise never deletes any note (see `pipeline/wikilinks.py`).
    try:
        from ..wikilinks import auto_fix_moved_wikilinks, resolve_acronym_links

        n_fixed = auto_fix_moved_wikilinks(vault_dir)
        if n_fixed > 0:
            _LOG.info(
                "[cycle %s] normalized wikilinks in %s file(s)",
                cycle_num,
                n_fixed,
            )
        # Spec 062 FR3: resolve title-derived acronym links + redirect stubs.
        n_acro = resolve_acronym_links(vault_dir)
        if n_acro > 0:
            _LOG.info(
                "[cycle %s] resolved acronym links in %s file(s)",
                cycle_num,
                n_acro,
            )
    except Exception as e:
        _LOG.warning("wikilink normalization failed: %s — continuing", e)
    return __exit


def run_research(ctx: CycleContext, scout_result: ScoutResult) -> ResearchResult:
    _ = scout_result
    t0 = time.monotonic()
    code = _phase(ctx)
    return dataclasses.replace(_collect_result(ctx, started_mono=t0), exit_code=code)


def research_result_from_disk(ctx: CycleContext) -> ResearchResult:
    """This cycle's research result WITHOUT dispatching (budget-marker §4.5).

    The counterpart to :func:`scout.scout_result_from_disk`, for a resume that
    starts after the research phase. Every field already comes off
    ``cycle-NNN-research.json``; the dispatch is what is skipped.
    """
    return _collect_result(ctx, started_mono=time.monotonic())


def _collect_result(ctx: CycleContext, *, started_mono: float) -> ResearchResult:
    t0 = started_mono
    cycle_3 = f"{ctx.cycle_num:03d}"
    research_report = ctx.cycles_dir / f"cycle-{cycle_3}-research.json"
    notes: list[Path] = []
    rejected: list[VerifierRejection] = []
    cost = 0.0
    cap = False
    if research_report.is_file():
        try:
            doc = json.loads(research_report.read_text(encoding="utf-8"))
            for rel in doc.get("notes_created") or []:
                notes.append((ctx.vault_dir / str(rel)).resolve())
            cap = bool(doc.get("note_writer_cap_tripped"))
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return ResearchResult(
        notes_written=notes,
        notes_rejected=rejected,
        duration_ms=int((time.monotonic() - t0) * 1000),
        cost_usd=cost,
        raw_json_path=research_report,
        note_writer_cap_tripped=cap,
    )
