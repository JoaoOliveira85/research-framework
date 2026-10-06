"""Tests for src/research_framework/generator/templates.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from research_framework.generator.templates import render_all
from research_framework.spec.parser import parse


def test_render_all_creates_claude_md(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(spec, vault)
    claude = (vault / "CLAUDE.md").read_text()
    # Spec name must appear (not boilerplate)
    assert "Test Vault" in claude
    assert "[PROJECT" not in claude  # no placeholder leakage
    # Note types rendered
    assert "concept" in claude.lower()
    # Search dimensions rendered
    assert "domain" in claude
    assert "market" in claude


def test_claude_md_scope_labels_include_and_exclude_correctly(
    tmp_path: Path,
) -> None:
    """v0.2.5/0.2.6 regression: simple-spec vaults mapped scope.exclude onto
    ScopeConfig.boundaries, so CLAUDE.md rendered every exclude item as
    'In scope'. This test pins the fix."""
    from research_framework.spec.simple import SimpleSpec, expand

    simple = SimpleSpec(
        name="Recipes",
        owner="t",
        topic="family meal prep",
        scope_include=["recipes that freeze well"],
        scope_exclude=["deep frying recipes"],
    )
    spec = expand(simple, location=tmp_path / "vault")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_templates").mkdir()
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    render_all(spec, vault)
    claude = (vault / "CLAUDE.md").read_text()
    assert "- In scope: recipes that freeze well" in claude
    assert "- Out of scope: deep frying recipes" in claude
    # Regression guard: exclude items must NOT appear as in-scope.
    assert "- In scope: deep frying recipes" not in claude


def test_claude_md_skips_hard_paragraph_when_no_hard_note_types(
    tmp_path: Path,
) -> None:
    """Non-code-first vaults have all-soft note types — the paragraph
    demanding a GitHub URL is meaningless and was leaking anyway before
    v0.2.7."""
    from research_framework.spec.simple import SimpleSpec, expand

    simple = SimpleSpec(
        name="Recipes",
        owner="t",
        topic="family meal prep",
        sources=[{"name": "Food From Portugal", "role": "recipes"}],
    )
    spec = expand(simple, location=tmp_path / "vault")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_templates").mkdir()
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    render_all(spec, vault)
    claude = (vault / "CLAUDE.md").read_text()
    assert "https://github.com/..." not in claude
    assert "code location" not in claude


def test_render_all_creates_agents_md(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(spec, vault)
    agents = (vault / "AGENTS.md").read_text()
    assert "Test Vault" in agents
    assert "01 - Concepts" in agents


def test_render_all_creates_note_type_templates(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    (vault / "_templates").mkdir(parents=True)
    render_all(spec, vault)
    for nt in spec.note_types:
        tpl = vault / "_templates" / f"{nt.name}.md"
        assert tpl.exists()
        content = tpl.read_text()
        for section in nt.required_sections:
            assert f"## {section}" in content


def test_render_all_creates_prompts(sample_spec_path: Path, tmp_path: Path) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    render_all(spec, vault)
    assert (vault / "_pipeline" / "prompts" / "scout-prompt.md").exists()
    assert (vault / "_pipeline" / "prompts" / "dfs-prompt.md").exists()


def test_render_all_creates_update_script(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = parse(sample_spec_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(spec, vault)
    update_script = vault / "update_vault.py"
    assert update_script.exists()
    text = update_script.read_text()
    assert "Maintain the generated vault in place" in text
    assert "refresh" in text


_SELF_KILLING_SCRIPT = "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n"


def _rendered_update_script(sample_spec_path: Path, tmp_path: Path) -> Path:
    """Render a vault's ``update_vault.py`` and give it a ``scripts/`` folder."""
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(parse(sample_spec_path), vault)
    (vault / "scripts").mkdir()
    return vault / "update_vault.py"


def _run_update_script(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True
    )


def test_update_script_validate_without_validators_is_an_error_not_a_pass(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Every missing validator was skipped, and having run none the script
    exited 0 — the bug the ``validate`` verb had (fc2c1ea)."""
    script = _rendered_update_script(sample_spec_path, tmp_path)

    result = _run_update_script(script, "validate")

    assert result.returncode == 2, f"stdout={result.stdout}"
    assert "no validator scripts found" in result.stderr


def test_update_script_validate_fails_on_a_signal_killed_validator(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """A child killed by a signal has a negative return code, and ``max()``
    over the codes dropped it: an OOM-killed validator read as a pass."""
    script = _rendered_update_script(sample_spec_path, tmp_path)
    (script.parent / "scripts" / "validate_vault.py").write_text(
        _SELF_KILLING_SCRIPT, encoding="utf-8"
    )

    result = _run_update_script(script, "validate")

    assert result.returncode == 2, f"stdout={result.stdout}"


def test_update_script_refresh_fails_on_a_signal_killed_metrics_run(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """``refresh`` ends on ``max(validate, metrics)``: the same dropped code."""
    script = _rendered_update_script(sample_spec_path, tmp_path)
    scripts = script.parent / "scripts"
    (scripts / "validate_vault.py").write_text("", encoding="utf-8")  # passes
    (scripts / "vault_metrics.py").write_text(_SELF_KILLING_SCRIPT, encoding="utf-8")
    (script.parent / "data_vault").mkdir()

    result = _run_update_script(script, "refresh")

    assert result.returncode == 2, f"stdout={result.stdout}"


# Code-first template tests (feature 002).


def _code_first_vault_path() -> Path:
    return (
        Path(__file__).parent.parent.parent
        / "tests"
        / "fixtures"
        / "specs"
        / "code-first-vault-spec.md"
    )


def _render_cf(tmp_path: Path):
    spec = parse(_code_first_vault_path())
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_templates").mkdir()
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    render_all(spec, vault)
    return spec, vault


def test_claude_md_renders_code_first_ordering(tmp_path: Path) -> None:
    """GitHub (priority=1) must appear before Confluence in Data Sources."""
    _, vault = _render_cf(tmp_path)
    claude = (vault / "CLAUDE.md").read_text()
    ds_section_start = claude.index("## Data Sources")
    # Truncate at the next heading
    ds_block = claude[ds_section_start:]
    ds_block = ds_block.split("\n## ", 1)[0]
    gh_pos = ds_block.find("GitHub repos")
    conf_pos = ds_block.find("Confluence")
    assert gh_pos != -1, "GitHub missing from Data Sources"
    assert conf_pos != -1, "Confluence missing from Data Sources"
    assert gh_pos < conf_pos, "GitHub must appear before Confluence"


def test_claude_md_includes_source_of_truth_rule(tmp_path: Path) -> None:
    _, vault = _render_cf(tmp_path)
    claude = (vault / "CLAUDE.md").read_text()
    assert "## Source-of-Truth Rule" in claude
    assert "Code wins" in claude


def test_vault_config_bfs_sources_ordered(tmp_path: Path) -> None:
    """bfs_sources must list primary (GitHub) before intent (Confluence)."""
    _, vault = _render_cf(tmp_path)
    cfg = (vault / "vault-config.yaml").read_text()
    assert "bfs_sources:" in cfg
    # Find positions of the source names (regex-free substring search is fine)
    gh_pos = cfg.find("github_repos")
    conf_pos = cfg.find("confluence")
    assert gh_pos != -1 and conf_pos != -1
    assert gh_pos < conf_pos


def test_agents_md_data_sources_priority_ordered(tmp_path: Path) -> None:
    _, vault = _render_cf(tmp_path)
    agents = (vault / "AGENTS.md").read_text()
    # Match the actual bullet lines (`- <name> (...)`), not prose intro text.
    bullets = [
        line
        for line in agents.splitlines()
        if line.startswith("- ") and ("priority" in line)
    ]
    # First bullet must be the primary behaviour source (GitHub).
    assert bullets, "No priority-tagged bullets found in AGENTS.md"
    assert "GitHub repos" in bullets[0]
    # Confluence bullet must appear after GitHub
    gh_idx = next(i for i, b in enumerate(bullets) if "GitHub repos" in b)
    conf_idx = next(i for i, b in enumerate(bullets) if "Confluence" in b)
    assert gh_idx < conf_idx


def test_service_template_includes_current_behaviour_and_stated_intent(
    tmp_path: Path,
) -> None:
    """Generated service.md template carries both required sections."""
    _, vault = _render_cf(tmp_path)
    service_tpl = (vault / "_templates" / "service.md").read_text()
    assert "## Current Behaviour" in service_tpl
    assert "## Stated Intent" in service_tpl


def test_scout_prompt_orders_repo_walk_first(tmp_path: Path) -> None:
    """First substantive section after headers must reference repo walks
    before Confluence. Code-first invariant."""
    _, vault = _render_cf(tmp_path)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    walk_pos = prompt.find("## Step 1 — Walk the enumerated repos")
    intent_pos = prompt.find("## Step 2 — Collect intent")
    assert walk_pos != -1, "Step 1 repo walk section missing"
    assert intent_pos != -1, "Step 2 intent section missing"
    assert walk_pos < intent_pos, "Repo walk must precede intent collection"
    # Step 1 block must mention each of the 9 enumerated repos by name
    step1_block = prompt[walk_pos:intent_pos]
    for repo in ("CAT", "LDG", "BAL", "CLR", "SET", "CFG", "RPT", "ONB", "REF"):
        assert repo in step1_block, f"repo {repo} missing from Step 1 walk list"


def test_scout_prompt_renders_v2_schema_section(tmp_path: Path) -> None:
    """The output-schema section must reference the v2 shape (schema_version:
    2.0, topics_from_code, intent_from_confluence, parent_code_topic_id)."""
    _, vault = _render_cf(tmp_path)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert '"schema_version": "2.0"' in prompt
    assert '"topics_from_code"' in prompt
    assert '"intent_from_confluence"' in prompt
    assert '"parent_code_topic_id"' in prompt


def test_scout_prompt_declares_canonical_source_file_shape(tmp_path: Path) -> None:
    """v0.2.27 regression: the scout prompt must give the agent unambiguous
    guidance to use the ``<org>/<repo>/<path>`` canonical shape derived from
    the repo's URL, NOT the on-disk filesystem path. v0.2.26 showed both
    URL and local_path with no preference; the scout occasionally copied
    the local_path shape (``acme-corp/backend/oebh-service/...``) and
    the validator rejected it. v0.2.27 fixes the validator to accept both
    shapes AND tightens the prompt so the canonical shape is the obvious
    choice going forward.
    """
    _, vault = _render_cf(tmp_path)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "source_file` shape (mandatory)" in prompt, (
        "scout prompt missing the canonical-shape callout"
    )
    assert "Canonical `source_file` prefix:" in prompt, (
        "scout prompt missing the per-repo canonical prefix derived from URL"
    )
    assert "Access (your filesystem, NOT for `source_file`):" in prompt, (
        "scout prompt must label the on-disk path as filesystem-only, not "
        "for inclusion in source_file"
    )


def test_scout_prompt_instructs_generalize_step_and_topics_found(
    tmp_path: Path,
) -> None:
    """Regression guard for the 017 SG-001 wiring bug.

    The CODE-FIRST prompt must (a) carry an explicit "generalize" step telling the
    scout to populate ``topics_found.new`` with engineering-concept titles, (b)
    include ``topics_found`` in the v2 JSON schema example, and (c) carry an
    explicit constraint that ``topics_found.new`` MUST be non-empty — otherwise
    the rendered prompt and the SG-001 gate disagree and every cycle aborts on
    Step 2 (which is exactly what happened on the first 017 dogfood run).
    """
    _, vault = _render_cf(tmp_path)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()

    assert "## Step 4 — Generalize" in prompt, (
        "CODE-FIRST scout prompt is missing the generalization step that produces "
        "topics_found.new — SG-001 will fail every cycle without it."
    )

    assert '"topics_found"' in prompt
    assert '"new"' in prompt
    assert '"coverage_category"' in prompt
    assert '"source_code_topic_ids"' in prompt

    assert "topics_found.new` MUST be non-empty" in prompt
    assert "SG-001" in prompt
    assert "SG-002" in prompt
    assert "SG-003" in prompt

    # Template version must be bumped so the migrator knows to re-render vaults
    # that were scaffolded against the v1 template (which omitted topics_found).
    assert "_template_version: 2" in prompt


def test_scout_prompt_renders_target_topics_when_supplied(tmp_path: Path) -> None:
    """Resume-run aid: when target_topics is passed, the prompt lists them."""
    from research_framework.generator.templates import render_all
    from research_framework.spec.parser import parse

    spec = parse(_code_first_vault_path())
    vault = tmp_path / "resume-vault"
    vault.mkdir()
    (vault / "_templates").mkdir()
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    render_all(
        spec,
        vault,
        target_topics=["OMS (Order Management Service).md", "Root Variant.md"],
        exclude_topics=["OEHK (Order Engine Housekeeper).md"],
    )
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "## Resume-run targets" in prompt
    assert "OMS (Order Management Service).md" in prompt
    assert "Root Variant.md" in prompt
    assert "## Already covered — skip these" in prompt
    assert "OEHK (Order Engine Housekeeper).md" in prompt


def test_scout_prompt_skips_resume_sections_when_empty(tmp_path: Path) -> None:
    """Default render (no target_topics) must NOT emit the resume section."""
    _, vault = _render_cf(tmp_path)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "## Resume-run targets" not in prompt
    assert "## Already covered" not in prompt


def test_ask_command_template_rendered(tmp_path: Path) -> None:
    """ask.md in .claude/commands/ must enforce the two-tier citation block."""
    _, vault = _render_cf(tmp_path)
    cmd = (vault / ".claude" / "commands" / "ask.md").read_text()
    # Frontmatter description references the vault
    assert "Codebase Vault (Code-First)" in cmd
    # Two-tier citation (Principle IX) must appear
    assert "Vault Sources:" in cmd
    assert "Original Sources:" in cmd
    # Vault Sources come before Original Sources
    assert cmd.find("Vault Sources:") < cmd.find("Original Sources:")


def test_research_command_template_rendered(tmp_path: Path) -> None:
    """research.md must surface hard-type enforcement and the 4 default hard types."""
    _, vault = _render_cf(tmp_path)
    cmd = (vault / ".claude" / "commands" / "research.md").read_text()
    assert "REJECTED" in cmd or "rejected" in cmd
    for t in ("service", "flow", "concept", "decision"):
        assert t in cmd
    # References the source-policy concept and code_source_url_patterns
    assert "source_policy" in cmd
    assert "code_source_url_patterns" in cmd


def test_write_command_template_rendered(tmp_path: Path) -> None:
    """write.md exists and writes into output/ (not data_vault/)."""
    _, vault = _render_cf(tmp_path)
    cmd = (vault / ".claude" / "commands" / "write.md").read_text()
    assert "output/" in cmd
    assert "data_vault/" in cmd  # at least to say "don't write here"
    # Two-tier citation enforced for documents too
    assert "Vault Sources" in cmd
    assert "Original Sources" in cmd


def test_command_filenames_follow_settings_commands(tmp_path: Path) -> None:
    """When spec.settings.commands renames a command, the rendered file renames too."""
    from research_framework.generator.templates import render_all
    from research_framework.spec.parser import parse
    from research_framework.spec.schema import CommandsConfig

    spec = parse(_code_first_vault_path())
    spec.settings.commands = CommandsConfig(
        ask="myteam", research="myteam-add", write="doc"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(spec, vault)
    assert (vault / ".claude" / "commands" / "myteam.md").exists()
    assert (vault / ".claude" / "commands" / "myteam-add.md").exists()
    assert (vault / ".claude" / "commands" / "doc.md").exists()
    # Default-named files must NOT exist in this mode.
    assert not (vault / ".claude" / "commands" / "ask.md").exists()


def test_regenerate_agents_preserves_the_generate_time_commands(
    tmp_path: Path,
) -> None:
    """`regenerate-agents` refreshes commands; it must not replace them.

    Nothing crossed generate → regenerate-agents before, which is why two
    incompatible templates could render to the same `.claude/commands/
    research.md` for months (#252).
    """
    from research_framework.agents import write_agents

    _, vault = _render_cf(tmp_path)
    commands_dir = vault / ".claude" / "commands"
    before = {p.name: p.read_text() for p in sorted(commands_dir.glob("*.md"))}

    write_agents(vault, parse(_code_first_vault_path()), overwrite=True)

    after = {p.name: p.read_text() for p in sorted(commands_dir.glob("*.md"))}
    assert set(after) == set(before), "regenerate changed the set of commands"
    for name in ("ask.md", "research.md", "write.md"):
        assert after[name] == before[name], f"{name} was replaced, not refreshed"


def test_regenerate_agents_preserves_a_renamed_command(tmp_path: Path) -> None:
    """A vault that renamed `/research` must not gain a second one."""
    from research_framework.agents import write_agents
    from research_framework.spec.schema import CommandsConfig

    spec = parse(_code_first_vault_path())
    spec.settings.commands = CommandsConfig(
        ask="myteam", research="myteam-add", write="doc"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    render_all(spec, vault)

    write_agents(vault, spec, overwrite=True)

    commands_dir = vault / ".claude" / "commands"
    assert (commands_dir / "myteam-add.md").exists()
    assert not (commands_dir / "research.md").exists()
    assert not (commands_dir / "ask.md").exists()


def test_render_scout_prompt_standalone_updates_only_the_prompt(
    tmp_path: Path,
) -> None:
    """render_scout_prompt() overwrites just the prompt file (resume use case)."""
    from research_framework.generator.templates import render_scout_prompt
    from research_framework.spec.parser import parse

    spec = parse(_code_first_vault_path())
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    # Pre-existing sentinel files MUST remain untouched after re-render.
    (vault / "_pipeline" / "cycles").mkdir()
    (vault / "_pipeline" / "cycles" / "sentinel.json").write_text("{}")

    render_scout_prompt(
        spec,
        vault,
        target_topics=["X.md", "Y.md"],
        exclude_topics=["Z.md"],
    )
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "## Resume-run targets" in prompt
    assert "X.md" in prompt
    assert "Y.md" in prompt
    assert "Z.md" in prompt
    # Nothing else clobbered
    assert (vault / "_pipeline" / "cycles" / "sentinel.json").exists()
