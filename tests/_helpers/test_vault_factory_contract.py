"""Contract test for ``tests/_helpers/vault_factory.py`` (feature 018, T014)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_framework.pipeline.settings import (
    effective_max_cycles,
    load_vault_settings,
)
from tests._helpers.vault_factory import build_minimal_vault


def test_factory_output_passes_validate_vault(tmp_path: Path) -> None:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=3,
        max_cycles=3,
    )
    assert (vault / "research.spec.md").is_file()
    assert (vault / "settings.yaml").is_file()
    assert (vault / "_pipeline" / "spec-parse.json").is_file()
    assert (vault / "_pipeline" / "coverage-targets.json").is_file()
    assert (vault / "_pipeline" / "research-plan.md").is_file()
    assert (vault / "_pipeline" / "prompts" / "scout-prompt.md").is_file()
    assert (vault / "_pipeline" / "prompts" / "dfs-prompt.md").is_file()
    assert (vault / "scripts" / "agent_call.py").is_file()
    assert (vault / "scripts" / "validate_cycle.py").is_file()

    targets = json.loads(
        (vault / "_pipeline" / "coverage-targets.json").read_text(encoding="utf-8")
    )
    assert len(targets["categories"]) == 2
    assert targets["categories"][0]["target_count"] == 3

    repo_root = Path(__file__).resolve().parents[2]
    validate_vault = repo_root / "scripts" / "validate_vault.py"
    proc = subprocess.run(
        [sys.executable, str(validate_vault), str(vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"validate_vault failed exit {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


def test_factory_installs_fake_agent_shim(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    shim = (vault / "scripts" / "agent_call.py").read_text(encoding="utf-8")
    assert "fake_agent" in shim, "shim should delegate to tests/_helpers/fake_agent"


def test_custom_settings_text_still_carries_factory_max_cycles(tmp_path: Path) -> None:
    """Regression #128: a caller-supplied ``settings_text`` that omits the
    spec-061 canonical pipeline budget keys must NOT make ``effective_max_cycles``
    silently fall back to ``DEFAULT_MAX_CYCLES`` (20).

    Pre-fix, the factory only baked its ``max_cycles`` param into the *default*
    settings; a custom body bypassed it, the settings failed to load (max_cycles
    + budget_usd are both required), and the cycle quota collapsed to 1 — which
    starved the scout/note-writer e2e scenarios. The factory now injects the
    canonical keys on the supplied path too.
    """
    custom_settings = (
        "pipeline:\n"
        "  gates:\n"
        "    cg_003_warn_pct: 30\n"
        "    cg_003_fail_pct: 60\n"
        "  note_writer_batch_size: 6\n"
        "default_executor:\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "  timeout_s: 60\n"
    )
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=2,
        settings_text=custom_settings,
    )

    # The settings must parse cleanly (both required budget keys present) ...
    settings = load_vault_settings(vault)
    assert settings.max_cycles == 2
    assert settings.budget_usd == 10.0
    # ... and the cycle-time horizon must reflect the factory's param, NOT the
    # generous built-in default that masked the regression.
    assert effective_max_cycles(vault) == 2


def test_factory_deterministic_categories(tmp_path: Path) -> None:
    v1 = build_minimal_vault(
        tmp_path / "a", num_categories=3, num_targets_per_category=4
    )
    v2 = build_minimal_vault(
        tmp_path / "b", num_categories=3, num_targets_per_category=4
    )
    t1 = json.loads((v1 / "_pipeline" / "coverage-targets.json").read_text())
    t2 = json.loads((v2 / "_pipeline" / "coverage-targets.json").read_text())
    cats1 = [(c["name"], c["target_count"]) for c in t1["categories"]]
    cats2 = [(c["name"], c["target_count"]) for c in t2["categories"]]
    assert cats1 == cats2
