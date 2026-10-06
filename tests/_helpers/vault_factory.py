"""Build minimal, real-looking research vaults on tmp_path (feature 018).

Used by the tier-4 / tier-5 end-to-end tests. The factory produces a vault that
the real :func:`research_framework.pipeline.cycle_runner.run_cycle_steps` can drive
without monkeypatching — the only test-only customization is that
``scripts/agent_call.py`` is replaced by the fake-agent shim (which still
satisfies the same CLI contract).

Contract: ``specs/018-testing-strategy/contracts/vault-factory.contract.md``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from research_framework.generator.scaffold import scaffold
from research_framework.generator.scripts import copy_scripts
from research_framework.generator.templates import render_all
from research_framework.pipeline.coverage import save_targets
from research_framework.pipeline.research_plan import generate_plan
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from tests._helpers import fake_agent

DEFAULT_SETTINGS_YAML = """\
pipeline:
  max_cycles: 5
  budget_usd: 10.0
  gates:
    cg_003_warn_pct: 30
    cg_003_fail_pct: 60
  note_writer_batch_size: 6
  max_batches_per_cycle: 10
  source_failure_thresholds:
    required_quorum_loss: 99
default_executor:
  runtime: claude
  model: sonnet
  timeout_s: 60
stages:
  verifier:
    enabled: false
"""


def _build_synthetic_spec(
    vault: Path,
    *,
    num_categories: int,
    num_targets_per_category: int,
    max_cycles: int,
    note_type_folder: str,
    out_of_scope: list[str] | None = None,
    overrides: dict | None = None,
) -> SpecConfig:
    """Construct a SpecConfig with a deterministic, configurable shape."""
    cats: list[CoverageCategory] = []
    cat_names = ["cat_a", "cat_b", "cat_c", "cat_d", "cat_e"]
    for i in range(num_categories):
        name = cat_names[i] if i < len(cat_names) else f"cat_{i}"
        cats.append(
            CoverageCategory(
                name=name,
                note_type="concept",
                target_count=num_targets_per_category,
                met_count=0,
                priority=90 - i * 5,
            )
        )
    scope = ScopeConfig(
        domain="test-domain",
        organization="test-org",
        out_of_scope=out_of_scope or ["crypto"],
    )
    spec = SpecConfig(
        name="fake-agent-vault",
        location=vault,
        owner="tests",
        scope=scope,
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="A synthetic concept note.",
                folder=note_type_folder,
                min_word_count=30,
            )
        ],
        data_sources=[
            DataSourceConfig(
                name="synthetic",
                type="external",
                description="Synthetic source for tests.",
                priority=2,
            )
        ],
        search_dimensions=["technical"],
        coverage_targets=CoverageTargets(categories=cats),
        budget=BudgetConfig(),
        forbidden_filename_prefixes=[],
    )
    if overrides:
        for key, value in overrides.items():
            setattr(spec, key, value)
    return spec


def _write_research_spec_md(vault: Path, spec: SpecConfig) -> None:
    """Write a minimal ``research.spec.md``. The cycle runner reads
    ``_pipeline/spec-parse.json`` for structured access; the md file is
    here so ``validate_vault.py`` / docs tooling don't complain."""
    body = (
        "---\n"
        f"name: {spec.name}\n"
        f"owner: {spec.owner}\n"
        "---\n\n"
        f"# {spec.name}\n\n"
        "Synthetic spec for feature-018 e2e tests.\n"
    )
    (vault / "research.spec.md").write_text(body, encoding="utf-8")


def _write_settings(vault: Path, settings_text: str | None = None) -> None:
    body = settings_text if settings_text is not None else DEFAULT_SETTINGS_YAML
    (vault / "settings.yaml").write_text(body, encoding="utf-8")


def _bake_pipeline_budget_keys(settings_body: str, max_cycles: int) -> str:
    """Force the spec-061 canonical pipeline budget keys into a settings body.

    Spec 061 moved the cycle horizon out of the research spec and into
    ``settings.yaml`` — and ``load_vault_settings`` REQUIRES both
    ``pipeline.max_cycles`` and ``pipeline.budget_usd``. A caller-supplied
    ``settings_text`` that omits them makes the loader raise ``SettingsError``,
    so cycle-time consumers like ``effective_max_cycles`` silently fall back to
    the generous built-in default (``DEFAULT_MAX_CYCLES`` = 20). The per-cycle
    yield quota then collapses to 1 and starves the scout / note-writer
    scenarios the e2e tests drive (regression #128).

    The factory's ``max_cycles`` parameter is authoritative, so it is always
    written; ``budget_usd`` is only defaulted (10.0, matching
    ``DEFAULT_SETTINGS_YAML``) when the body omits it. Round-trips through YAML
    because a plain string-replace cannot inject an absent key; returns the
    body unchanged on any parse error.
    """
    try:
        data = yaml.safe_load(settings_body)
    except yaml.YAMLError:
        return settings_body
    if not isinstance(data, dict):
        return settings_body
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        pipeline = {}
        data["pipeline"] = pipeline
    pipeline["max_cycles"] = max_cycles
    pipeline.setdefault("budget_usd", 10.0)
    return yaml.safe_dump(data, sort_keys=False)


def _generate_initial_plan(vault: Path, spec: SpecConfig) -> Path:
    """Write ``_pipeline/research-plan.md`` so the batched DFS path activates."""
    plan = generate_plan(vault, spec, cycle_number=1)
    out = vault / "_pipeline" / "research-plan.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(plan.to_markdown(), encoding="utf-8")
    return out


def build_minimal_vault(
    tmp_path: Path,
    *,
    num_categories: int = 3,
    num_targets_per_category: int = 5,
    max_cycles: int = 5,
    note_type_folder: str = "01 - Concepts",
    out_of_scope: list[str] | None = None,
    spec_overrides: dict | None = None,
    install_fake_agent: bool = True,
    settings_text: str | None = None,
    note_writer_batch_size: int | None = None,
) -> Path:
    """Build a fresh test vault under ``tmp_path / "vault"``. See the contract doc."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)

    spec = _build_synthetic_spec(
        vault,
        num_categories=num_categories,
        num_targets_per_category=num_targets_per_category,
        max_cycles=max_cycles,
        note_type_folder=note_type_folder,
        out_of_scope=out_of_scope,
        overrides=spec_overrides,
    )

    scaffold(spec, vault, spec_source=None, settings_source=None)
    render_all(spec, vault)
    copy_scripts(vault)

    if install_fake_agent:
        fake_agent.install_shim(vault / "scripts")

    save_targets(vault, spec.coverage_targets)

    settings_body = settings_text
    if settings_body is None:
        # Spec 061: the cycle horizon the yield model reads now lives in
        # settings.yaml (pipeline.max_cycles), not the spec — so the factory's
        # max_cycles param must be baked here to preserve e2e yield behaviour.
        settings_body = DEFAULT_SETTINGS_YAML
        if note_writer_batch_size is not None:
            settings_body = settings_body.replace(
                "note_writer_batch_size: 6",
                f"note_writer_batch_size: {note_writer_batch_size}",
            )
        if max_cycles != 5:
            settings_body = settings_body.replace(
                "max_cycles: 5", f"max_cycles: {max_cycles}", 1
            )
    else:
        # Regression #128: a caller-supplied settings_text must STILL carry the
        # spec-061 canonical pipeline budget keys (max_cycles + budget_usd).
        # Without them load_vault_settings raises, effective_max_cycles() falls
        # back to DEFAULT_MAX_CYCLES (20), the per-cycle quota collapses to 1,
        # and scout/note-writer e2e scenarios never get exercised.
        settings_body = _bake_pipeline_budget_keys(settings_body, max_cycles)
    _write_settings(vault, settings_body)

    _write_research_spec_md(vault, spec)

    parse_path = vault / "_pipeline" / "spec-parse.json"
    parse_doc: dict[str, Any] = spec.to_dict()
    parse_doc["location"] = str(vault.resolve())
    parse_path.write_text(json.dumps(parse_doc, indent=2) + "\n", encoding="utf-8")

    _generate_initial_plan(vault, spec)

    return vault


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        return ""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _quality_settings_yaml(vault_dir: Path, *, note_count_target: int) -> str:
    responses_dir = (vault_dir / "fake_agent_responses").resolve()
    return (
        "pipeline:\n"
        "  max_cycles: 3\n"
        "  budget_usd: 10.0\n"
        "  gates:\n"
        "    cg_003_warn_pct: 30\n"
        "    cg_003_fail_pct: 60\n"
        "  note_writer_batch_size: 6\n"
        "  max_batches_per_cycle: 10\n"
        f"  note_count_target: {note_count_target}\n"
        "cycle:\n"
        "  runner:\n"
        f'    fake_agent_responses_dir: "{responses_dir}"\n'
        "    max_cycles: 3\n"
        "default_executor:\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "  timeout_s: 60\n"
        "stages:\n"
        "  verifier:\n"
        "    enabled: true\n"
    )


def _quality_fixture_manifest_path(vault: Path) -> Path:
    return vault / ".quality-fixture-bootstrap.json"


def _quality_fixture_inputs_fingerprint(
    *,
    spec_yaml: str,
    settings_text: str,
    coverage_text: str,
    fake_agent_responses_src: Path | None,
) -> dict[str, str]:
    return {
        "spec_sha256": _sha256_text(spec_yaml),
        "settings_sha256": _sha256_text(settings_text),
        "coverage_sha256": _sha256_text(coverage_text),
        "fake_agent_sha256": _tree_digest(fake_agent_responses_src)
        if fake_agent_responses_src
        else "",
    }


def build_quality_fixture(
    name: str,
    vault_dir: Path,
    *,
    spec_yaml: str,
    note_count_target: int,
    fake_agent_responses_src: Path | None = None,
) -> Path:
    """Bootstrap a committed quality-harness fixture vault (spec 022, research § D6).

    Writes ``research.spec.md``, ``settings.yaml``, ``coverage-targets.json``,
    ``_templates/``, and optionally copies a ``fake_agent_responses/`` tree.
    Re-running is a no-op when on-disk content already matches the inputs.
    """
    from research_framework.generator.scaffold import scaffold
    from research_framework.generator.scripts import copy_scripts
    from research_framework.generator.templates import render_all
    from research_framework.spec.parser import parse

    _ = name  # reserved for logging / future per-fixture defaults
    vault = Path(vault_dir).resolve()
    vault.mkdir(parents=True, exist_ok=True)

    spec_path = vault / "research.spec.md"
    settings_path = vault / "settings.yaml"
    coverage_path = vault / "coverage-targets.json"
    responses_dest = vault / "fake_agent_responses"
    manifest_path = _quality_fixture_manifest_path(vault)

    settings_text = _quality_settings_yaml(vault, note_count_target=note_count_target)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_spec = Path(tmp) / "research.spec.md"
        tmp_spec.write_text(spec_yaml, encoding="utf-8")
        spec = parse(tmp_spec)
    spec.location = vault
    coverage_text = json.dumps(spec.coverage_targets.to_dict(), indent=2) + "\n"

    fingerprint = _quality_fixture_inputs_fingerprint(
        spec_yaml=spec_yaml,
        settings_text=settings_text,
        coverage_text=coverage_text,
        fake_agent_responses_src=fake_agent_responses_src,
    )
    if manifest_path.is_file():
        try:
            recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            recorded = {}
        if recorded.get("inputs") == fingerprint:
            return vault

    spec_path.write_text(spec_yaml, encoding="utf-8")

    settings_tmp = vault / ".quality-settings.tmp.yaml"
    settings_tmp.write_text(settings_text, encoding="utf-8")
    try:
        scaffold(spec, vault, spec_source=spec_path, settings_source=settings_tmp)
        render_all(spec, vault)
        copy_scripts(vault)
        fake_agent.install_shim(vault / "scripts")
    finally:
        settings_tmp.unlink(missing_ok=True)

    coverage_path.write_text(coverage_text, encoding="utf-8")
    settings_path.write_text(settings_text, encoding="utf-8")

    if fake_agent_responses_src is not None:
        src = Path(fake_agent_responses_src).resolve()
        if not src.is_dir():
            raise FileNotFoundError(f"fake_agent_responses_src not found: {src}")
        if _tree_digest(src) != _tree_digest(responses_dest):
            if responses_dest.exists():
                shutil.rmtree(responses_dest)
            shutil.copytree(src, responses_dest)

    manifest_path.write_text(
        json.dumps({"inputs": fingerprint}, indent=2) + "\n",
        encoding="utf-8",
    )
    return vault


def install_bundled_skill(vault: Path, skill_name: str) -> Path:
    """Copy a bundled SKILL.md into the vault under ``.agents/skills/<name>/``.

    The factory does not install skills by default because ``skill_check``
    treats a missing ``.agents/skills/`` as a no-op pass. Tests that
    exercise the auto-repair path call this helper explicitly.
    """
    from research_framework._assets import asset_path

    src = asset_path(".agents") / "skills" / skill_name / "SKILL.md"
    if not src.is_file():
        raise FileNotFoundError(f"bundled skill not found: {src}")
    dest_dir = vault / ".agents" / "skills" / skill_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    shutil.copy2(src, dest)
    return dest


__all__ = (
    "DEFAULT_SETTINGS_YAML",
    "build_minimal_vault",
    "build_quality_fixture",
    "install_bundled_skill",
)
