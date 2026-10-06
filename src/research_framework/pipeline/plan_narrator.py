"""Advisory narrative header for `_pipeline/research-plan.md` (R-005, feature 017).

Fills ``## Focus rationale`` via ``scripts/agent_call.py`` (spec 025 A1). On failure,
writes a canned cycle-priority line and appends to ``_pipeline/narrator-incidents.md``.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

from research_framework.pipeline.settings import SettingsError, load_vault_settings

from ..spec.parser import parse
from ..spec.schema import SpecValidationError
from .research_plan import ResearchPlan

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _bootstrap_scripts_agent_call(vault_dir: Path | None = None):
    """Load ``scripts/agent_call.py`` as importable ``scripts.agent_call``.

    Resolution order (newest path wins, no cache pollution between vaults
    when a shim is in play):

    1. ``<vault_dir>/scripts/agent_call.py`` if it exists — lets the
       fake-agent shim (``tests/_helpers/fake_agent.install_shim``)
       intercept in-process dispatch during fixture cycles, matching
       the subprocess-CLI interception path that scout / research /
       verifier already get. Loaded under a vault-scoped module name
       so a repo-wide cached real agent_call does not shadow it.
    2. ``<repo_root>/scripts/agent_call.py`` — production path.
    3. ``<wheel>/_data/scripts/agent_call.py`` — installed-wheel
       fallback when the repo source tree is not on disk.
    """
    if vault_dir is not None:
        vault_shim = vault_dir / "scripts" / "agent_call.py"
        if vault_shim.is_file():
            mod_name = (
                f"scripts.agent_call.vault.{abs(hash(str(vault_shim.resolve())))}"
            )
            spec = importlib.util.spec_from_file_location(mod_name, vault_shim)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
                return module

    name = "scripts.agent_call"
    if name in sys.modules:
        return sys.modules[name]
    script_path = _REPO_ROOT / "scripts" / "agent_call.py"
    if not script_path.is_file():
        packaged = (
            Path(__file__).resolve().parents[1] / "_data" / "scripts" / "agent_call.py"
        )
        if packaged.is_file():
            script_path = packaged
    spec = importlib.util.spec_from_file_location(name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load agent_call from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_vault_tier(vault_dir: Path, stage: str) -> str:
    """Read ``stages.<stage>.tier`` via :func:`load_vault_settings` (spec 025 B7)."""
    try:
        return load_vault_settings(vault_dir).stage(stage).tier
    except SettingsError:
        return "standard"


def _skill_instructions() -> str:
    here = Path(__file__).resolve().parent
    repo_root = here.parent.parent.parent
    candidates = [
        here.parent
        / "_data"
        / ".agents"
        / "skills"
        / "research-plan-narrator"
        / "SKILL.md",
        repo_root / ".agents" / "skills" / "research-plan-narrator" / "SKILL.md",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return (
        "You are the research-plan narrator. Output at most 200 words of plain "
        "Markdown prose (no headings). Explain why the current cycle focus and "
        "priority queue matter. Never output section headings like "
        "## Coverage state."
    )


def _scope_summary(vault_dir: Path) -> str:
    spec_path = vault_dir / "research.spec.md"
    if not spec_path.is_file():
        return ""
    try:
        spec = parse(spec_path)
    except (OSError, SpecValidationError, ValueError):
        return ""
    lines: list[str] = []
    b = spec.scope.boundaries[:8] if spec.scope.boundaries else []
    o = spec.scope.out_of_scope[:8] if spec.scope.out_of_scope else []
    if b:
        lines.append("Scope boundaries (abridged): " + "; ".join(b))
    if o:
        lines.append("Out of scope (abridged): " + "; ".join(o))
    return "\n".join(lines)


def _truncate_words(text: str, max_words: int) -> str:
    parts = text.split()
    if len(parts) <= max_words:
        return text.strip()
    return " ".join(parts[:max_words])


def _atomic_write_text(path: Path, content: str) -> None:
    from .atomic_write import write_text

    write_text(path, content)


def _append_incident(vault_dir: Path, message: str) -> None:
    log_path = vault_dir / "_pipeline" / "narrator-incidents.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")


def _build_prompt(
    *,
    excerpt_from_coverage: str,
    cycle_focus: list[str],
    scope_blurb: str,
) -> str:
    focus_line = (
        "Cycle focus categories: " + ", ".join(cycle_focus) if cycle_focus else ""
    )
    parts = [
        _skill_instructions(),
        "---",
        scope_blurb,
        focus_line,
        "---",
        "Deterministic plan excerpt (read-only context; do not reproduce headings):",
        excerpt_from_coverage.strip(),
    ]
    return "\n\n".join(p for p in parts if p).strip() + "\n"


def _splice_focus_rationale(original: str, rationale: str) -> str:
    focus = "## Focus rationale"
    cov = "## Coverage state"
    fi = original.find(focus)
    ci = original.find(cov)
    if fi < 0 or ci < 0 or fi >= ci:
        raise ValueError(
            "malformed plan: missing Focus rationale / Coverage state boundary"
        )
    line_start = original.rfind("\n", 0, fi) + 1
    prefix = original[:line_start]
    tail = original[ci:]
    body = rationale.strip()
    return f"{prefix}## Focus rationale\n\n{body}\n\n{tail}"


def prepend_narrative(vault_dir: Path, cycle_number: int) -> None:
    """Fill or replace ``## Focus rationale`` via ``agent_call.dispatch`` (spec 025 A1).

    Preserves bytes from ``## Coverage state`` through EOF. On dispatch failure, uses a
    canned cycle-priority line and records the incident under ``_pipeline/``.
    """
    plan_path = vault_dir / "_pipeline" / "research-plan.md"
    raw = plan_path.read_text(encoding="utf-8")
    parsed = ResearchPlan.from_markdown(raw)
    cycle_focus = list(parsed.cycle_focus)

    cov = "## Coverage state"
    ci = raw.find(cov)
    if ci < 0:
        raise ValueError("malformed plan: missing ## Coverage state")
    excerpt = raw[ci:]
    prompt = _build_prompt(
        excerpt_from_coverage=excerpt,
        cycle_focus=cycle_focus,
        scope_blurb=_scope_summary(vault_dir),
    )

    cycle_dir = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_number:03d}"
    tier = _load_vault_tier(vault_dir, "plan_narrator")
    agent_call = _bootstrap_scripts_agent_call(vault_dir=vault_dir)

    rationale_text: str | None = None
    failure_note: str | None = None
    try:
        call_result = agent_call.dispatch(
            stage="plan_narrator",
            prompt=prompt,
            tier=tier,
            vault_dir=vault_dir,
            cycle_dir=cycle_dir,
            timeout_s=60,
        )
    except Exception as exc:
        failure_note = f"agent dispatch failed: {exc}"
    else:
        if call_result.exit_code != 0:
            failure_note = f"agent exited {call_result.exit_code}"
        elif not (call_result.stdout or "").strip():
            failure_note = "agent returned empty stdout"
        else:
            rationale_text = _truncate_words(call_result.stdout, 200)

    if failure_note is not None:
        _append_incident(vault_dir, failure_note)
        top3 = ", ".join(cycle_focus[:3])
        rationale_text = f"Cycle {cycle_number} priority: {top3}"

    assert rationale_text is not None
    updated = _splice_focus_rationale(raw, rationale_text)
    _atomic_write_text(plan_path, updated)
