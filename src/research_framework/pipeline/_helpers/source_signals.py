"""Source degradation notifications, settings probes, and probe-retrieval staging."""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

import yaml

from ._probe_staging import (  # noqa: F401
    _probe_retrieval_enabled,
    _run_probe_retrieval_and_cache,
)
from .cycle_state import CycleRuntimeState

_LOG = logging.getLogger(__name__)


def _load_spec_for_scout_gates(vault_dir: Path):
    """Parsed vault spec for SG-001..003, or None to skip scout gates (no-spec path)."""
    from research_framework.spec.schema import SpecConfig

    parse_path = vault_dir / "_pipeline" / "spec-parse.json"
    if parse_path.is_file():
        try:
            return SpecConfig.from_dict(
                json.loads(parse_path.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, TypeError, KeyError, OSError):
            pass
    spec_md = vault_dir / "research.spec.md"
    if not spec_md.is_file():
        return None
    try:
        from research_framework.spec.simple import load as load_spec

        return load_spec(spec_md, location=vault_dir)
    except Exception:
        return None


def _cycle_quota_for_gates(pipeline_dir: Path) -> int:
    plan_path = pipeline_dir / "research-plan.md"
    if not plan_path.is_file():
        return 1
    try:
        from ..research_plan import ResearchPlan

        plan = ResearchPlan.from_markdown(plan_path.read_text(encoding="utf-8"))
        q = int(plan.cycle_quota)
        return q if q >= 1 else 1
    except Exception:
        return 1


def _unfilled_categories_for_gates(vault_dir: Path) -> int:
    try:
        from ..coverage import load_targets

        targets = load_targets(vault_dir)
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
        return 0
    return sum(1 for c in targets.categories if c.met_count < c.target_count)


def notify_required_source_degraded(
    vault_dir: Path,
    source_name: str,
    *,
    role: str,
    reason: str,
    runtime_state: CycleRuntimeState,
) -> int | None:
    """Record a mid-run source degradation (T074). Returns ``2`` when threshold trips."""
    if role == "enrichment":
        _LOG.warning(
            "[sources] enrichment source degraded (not counted toward "
            "required quorum): %s — %s",
            source_name,
            reason,
        )
        return None

    # FR-001: call mark_degraded with the correct 3-arg signature (the in-scope
    # vault_dir). The except is narrowed to OSError so a genuine I/O failure
    # writing source-incidents.md is tolerated, but an arity/signature mismatch
    # (TypeError) surfaces loudly instead of being swallowed as a warning — it's
    # a programming error, not a runtime source failure.
    from research_framework.pipeline import source_manager as _sm

    md = getattr(_sm, "mark_degraded", None)
    if callable(md):
        try:
            md(source_name, reason, vault_dir)
        except OSError as exc:
            _LOG.warning("[sources] mark_degraded I/O failure: %s", exc)

    def _threshold_from_pipe(pipe: dict) -> int | None:
        sft = pipe.get("source_failure_thresholds") or {}
        if isinstance(sft, dict) and sft.get("required_quorum_loss") is not None:
            try:
                return int(sft["required_quorum_loss"])
            except (TypeError, ValueError):
                return None
        if pipe.get("required_source_failure_threshold") is not None:
            try:
                return int(pipe["required_source_failure_threshold"])
            except (TypeError, ValueError):
                return None
        return None

    threshold = 2
    t_override = _threshold_from_pipe(
        _load_yaml_settings(vault_dir / "settings.yaml").get("pipeline") or {}
    )
    if t_override is not None:
        threshold = t_override
    else:
        try:
            from research_framework._assets import default_settings_path

            t2 = _threshold_from_pipe(
                _load_yaml_settings(default_settings_path()).get("pipeline") or {}
            )
            if t2 is not None:
                threshold = t2
        except (FileNotFoundError, OSError):
            pass

    cycle_guess = 1
    cdir = vault_dir / "_pipeline" / "cycles"
    if cdir.is_dir():
        best = 0
        for p in cdir.glob("cycle-*-research.json"):
            m = re.search(r"cycle-(\d+)-research\.json$", p.name)
            if m:
                best = max(best, int(m.group(1)))
        if best:
            cycle_guess = best

    cdir.mkdir(parents=True, exist_ok=True)
    inc_path = cdir / f"cycle-{cycle_guess:03d}-source-incidents.json"
    doc: dict = {"count": 0}
    if inc_path.is_file():
        try:
            doc = json.loads(inc_path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            doc = {"count": 0}
    n = int(doc.get("count") or 0) + 1
    doc["count"] = n
    from ..atomic_write import write_json as _write_json

    _write_json(inc_path, doc)

    if n >= threshold:
        runtime_state.should_abort = True
        return 2
    _LOG.warning(
        "[sources] required source degraded (%s/%s): %s — %s",
        n,
        threshold,
        source_name,
        reason,
    )
    return None


def _load_yaml_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError, TypeError):
        return {}


def _pipeline_int_setting(vault_dir: Path, key: str, default: int) -> int:
    for path in (vault_dir / "settings.yaml",):
        if not path.is_file():
            break
        pipe = _load_yaml_settings(path).get("pipeline") or {}
        if pipe.get(key) is not None:
            try:
                return int(pipe[key])
            except (TypeError, ValueError):
                break
        break
    try:
        from research_framework._assets import default_settings_path

        pipe = _load_yaml_settings(default_settings_path()).get("pipeline") or {}
        if pipe.get(key) is not None:
            return int(pipe[key])
    except (FileNotFoundError, OSError, TypeError, ValueError):
        pass
    return default


def _effective_note_writer_batch_size(vault_dir: Path, plan) -> int:
    """Match scheduler batch size to quota when invocations may under-yield notes."""
    configured = _pipeline_int_setting(vault_dir, "note_writer_batch_size", default=6)
    configured = max(3, min(10, int(configured)))
    quota = int(plan.cycle_quota)
    topic_cap = min(quota, len(plan.priority_queue))
    if topic_cap <= 0:
        return configured
    yield_floor = max(1, min(configured, 4))
    min_invocations = max(1, math.ceil(quota / yield_floor))
    eff = max(3, min(10, math.ceil(topic_cap / min_invocations)))
    return min(configured, eff)


def _max_batches_per_cycle(vault_dir: Path) -> int:
    return max(1, _pipeline_int_setting(vault_dir, "max_batches_per_cycle", default=10))
