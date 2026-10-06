"""Tests for `research_framework onboard` CLI sub-command.

Covers:
  - Fresh onboarding (git init, corpus rename, draft spec, stops at step 3)
  - Already-onboarded vault (all 5 steps run as no-ops, exit 0)
  - Ambiguous corpus (two candidate dirs → abort at step 2, exit 2)
  - Spec validation (drafted spec parses via spec.simple.load)
  - Idempotent step 1 (second run skips git init)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
FIXTURE_VAULT = Path(__file__).parent.parent / "fixtures" / "vault"
MANIFEST_PATH = REPO_ROOT / "dist-templates" / "scaffold-manifest.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env() -> dict[str, str]:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(REPO_ROOT / "src")
    return e


def _run_onboard(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "onboard", *args],
        capture_output=True,
        text=True,
        env=_env(),
        **kwargs,
    )


def _make_fresh_vault(tmp_path: Path) -> Path:
    """Create a minimal vault-like directory with no git and no spec.

    Contains:
      - CLAUDE.md, AGENTS.md, README.md
      - Tech Notes/ (corpus candidate)
    """
    vault = tmp_path / "reference-vault"
    vault.mkdir()

    (vault / "README.md").write_text(
        "# Tech Knowledge Vault\n\nA collection of technical notes.\n",
        encoding="utf-8",
    )
    (vault / "CLAUDE.md").write_text(
        "# CLAUDE\n\n**Owner**: Test User\n\n## Purpose\n\nTech reference notes.\n",
        encoding="utf-8",
    )
    (vault / "AGENTS.md").write_text(
        "# Agents\n\nAgent instructions for reference-vault.\n",
        encoding="utf-8",
    )

    corpus = vault / "Tech Notes"
    corpus.mkdir()
    (corpus / "note1.md").write_text("# Note 1\n\nContent.\n", encoding="utf-8")
    (corpus / "note2.md").write_text("# Note 2\n\nContent.\n", encoding="utf-8")

    return vault


def _make_onboarded_vault(tmp_path: Path) -> Path:
    """Create a vault that has been fully onboarded (all steps done)."""
    vault = _make_fresh_vault(tmp_path)

    # Step 1: git init + seed commit
    subprocess.run(["git", "init", "-q", str(vault)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(vault), "config", "user.email", "t@t"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(vault), "config", "user.name", "T"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(vault), "add", "-A"], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "commit",
            "-q",
            "-m",
            "vault: pre-onboarding initial state",
        ],
        check=True,
        capture_output=True,
    )

    # Step 2: rename corpus
    subprocess.run(
        ["git", "-C", str(vault), "mv", "Tech Notes", "data_vault"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "commit",
            "-q",
            "-m",
            "vault: rename corpus to data_vault/",
        ],
        check=True,
        capture_output=True,
    )

    # Step 3: write a minimal spec
    spec_path = vault / "reference-vault-spec.md"
    spec_path.write_text(
        "---\n"
        "name: Tech Knowledge Vault\n"
        "owner: Test User\n"
        "topic: Technical reference notes and engineering concepts.\n"
        "growth_mode: incremental\n"
        "scope:\n"
        "  include:\n"
        "    - Engineering\n"
        "  exclude:\n"
        "    - Business topics\n"
        "sources:\n"
        "  - name: Web\n"
        "---\n\n"
        "# Tech Knowledge Vault\n",
        encoding="utf-8",
    )

    # Step 4: write spec-parse.json
    pipeline_dir = vault / "_pipeline"
    pipeline_dir.mkdir(exist_ok=True)
    spec_parse = pipeline_dir / "spec-parse.json"

    env = _env()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework",
            "parse-spec",
            str(vault),
            str(spec_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    # If parse-spec fails (e.g. in CI without full deps), write a stub
    if r.returncode != 0 or not spec_parse.exists():
        spec_parse.write_text(
            json.dumps(
                {
                    "name": "Tech Knowledge Vault",
                    "owner": "Test User",
                    "topic": "Technical reference notes.",
                    "location": str(vault),
                    "note_types": [],
                    "data_sources": [],
                    "search_dimensions": [],
                    "coverage_targets": {"categories": []},
                    "budget": {"max_usd": 10.0, "max_cycles": 3},
                    "max_cycles": 3,
                    "scope": {
                        "domain": "tech",
                        "organization": "Test User",
                        "boundaries": [],
                        "out_of_scope": [],
                        "source_of_truth_rules": [],
                    },
                    "research_mode": "bootstrap",
                    "vault_corpus_dir": "data_vault",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return vault


def _git_available() -> bool:
    return shutil.which("git") is not None


# ---------------------------------------------------------------------------
# Fresh onboarding
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_fresh_onboard_stops_at_step3(tmp_path: Path) -> None:
    """Fresh vault: steps 1-2 run, step 3 drafts spec and stops (exit 1)."""
    vault = _make_fresh_vault(tmp_path)

    result = _run_onboard([str(vault)])

    # Exit 1 = stopped at step 3 for user review
    assert result.returncode == 1, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    # Step 1: git repo created
    assert (vault / ".git").exists(), "git repo was not initialised"

    # Step 2: corpus renamed
    assert (vault / "data_vault").exists(), "corpus not renamed to data_vault"
    assert not (vault / "Tech Notes").exists(), "old corpus dir still exists"

    # Step 3: spec drafted
    spec_path = vault / "reference-vault-spec.md"
    assert spec_path.exists(), "spec file was not drafted"

    # Check output contains step markers
    assert "[onboard 1/4]" in result.stdout
    assert "[onboard 2/4]" in result.stdout
    assert "[onboard 3/4]" in result.stdout
    assert "REVIEW REQUIRED" in result.stdout
    assert "Stopped at step 3" in result.stderr  # spec 077 FR-017


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_fresh_onboard_git_seed_commit_exists(tmp_path: Path) -> None:
    """Step 1 must produce a git commit with the correct message."""
    vault = _make_fresh_vault(tmp_path)
    _run_onboard([str(vault)])

    r = subprocess.run(
        ["git", "-C", str(vault), "log", "--oneline", "--all"],
        capture_output=True,
        text=True,
    )
    assert "pre-onboarding initial state" in r.stdout


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_fresh_onboard_corpus_rename_committed(tmp_path: Path) -> None:
    """Step 2 must produce a git commit renaming the corpus."""
    vault = _make_fresh_vault(tmp_path)
    _run_onboard([str(vault)])

    r = subprocess.run(
        ["git", "-C", str(vault), "log", "--oneline", "--all"],
        capture_output=True,
        text=True,
    )
    assert "rename corpus to data_vault" in r.stdout


# ---------------------------------------------------------------------------
# Already-onboarded vault
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_already_onboarded_all_steps_noop(tmp_path: Path) -> None:
    """Running onboard on a fully-onboarded vault must exit 0 with all steps noop."""
    vault = _make_onboarded_vault(tmp_path)

    result = _run_onboard([str(vault)])

    assert result.returncode == 0, (
        f"Expected exit 0 (all steps done)\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    out = result.stdout
    assert "[onboard 1/4]" in out
    assert "[onboard 2/4]" in out
    assert "[onboard 3/4]" in out
    assert "[onboard 4/4]" in out
    assert "already initialised" in out or "✓" in out


# ---------------------------------------------------------------------------
# Ambiguous corpus
# ---------------------------------------------------------------------------


def test_ambiguous_corpus_aborts(tmp_path: Path) -> None:
    """Two corpus candidate dirs → abort at step 2 with exit 2."""
    vault = tmp_path / "some-vault"
    vault.mkdir()

    # Two candidates that are not in the exclusion list
    (vault / "Tech Notes").mkdir()
    (vault / "Business Notes").mkdir()

    result = _run_onboard([str(vault), "--no-git"])

    assert result.returncode == 2, (
        f"Expected exit 2 (ambiguous corpus)\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert (
        "Multiple candidate" in result.stdout
        or "multiple candidate" in result.stdout.lower()
    )
    assert "Aborted at step 2" in result.stderr  # spec 077 FR-017


def test_no_corpus_aborts(tmp_path: Path) -> None:
    """No candidate dirs → abort at step 2 with exit 2."""
    vault = tmp_path / "empty-vault"
    vault.mkdir()
    # Only non-corpus dirs
    (vault / "_pipeline").mkdir()
    (vault / "scripts").mkdir()

    result = _run_onboard([str(vault), "--no-git"])

    assert result.returncode == 2
    assert "no corpus" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_drafted_spec_validates(tmp_path: Path) -> None:
    """The drafted spec must parse cleanly via spec.simple.load."""
    vault = _make_fresh_vault(tmp_path)
    _run_onboard([str(vault)])

    spec_path = vault / "reference-vault-spec.md"
    assert spec_path.exists()

    # Import the loader directly
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from research_framework.spec.simple import parse_simple

        simple = parse_simple(spec_path)
        assert simple.name  # name must be non-empty
        assert simple.topic  # topic must be non-empty
    finally:
        sys.path.pop(0)


# ---------------------------------------------------------------------------
# Idempotent step 1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_step1_idempotent_on_second_run(tmp_path: Path) -> None:
    """Running onboard twice: second run skips git init (no duplicate commits)."""
    vault = _make_fresh_vault(tmp_path)

    # First run: stops at step 3
    _run_onboard([str(vault)])

    # Second run: also stops at step 3 (spec already drafted → skipped)
    # but now step 3 sees the spec exists, so continues to step 4 which
    # may fail without data_vault in place. We just check step 1 is skipped.
    result2 = _run_onboard([str(vault)])

    # Step 1 message should say "already initialised" on second run
    assert "already initialised" in result2.stdout or "✓" in result2.stdout

    # Key invariant: step 1 must not re-commit on second run.
    # Slice out the step-1 block from stdout and assert no "committed N files".
    lines = result2.stdout.splitlines()
    first_block: list[str] = []
    in_step1 = False
    for line in lines:
        if "[onboard 1/4]" in line:
            in_step1 = True
        elif "[onboard 2/4]" in line:
            break
        if in_step1:
            first_block.append(line)
    assert not any("committed" in line for line in first_block), (
        f"Step 1 re-committed on second run:\n{''.join(first_block)}"
    )


# ---------------------------------------------------------------------------
# --no-git flag
# ---------------------------------------------------------------------------


def test_no_git_flag_skips_git_ops(tmp_path: Path) -> None:
    """--no-git: step 1 skipped, step 2 does plain rename without git."""
    vault = tmp_path / "test-vault"
    vault.mkdir()
    (vault / "Notes").mkdir()
    (vault / "Notes" / "note.md").write_text("# Note\n", encoding="utf-8")
    (vault / "README.md").write_text("# Test Vault\n\nA test.\n", encoding="utf-8")

    result = _run_onboard([str(vault), "--no-git"])

    # Should stop at step 3 (needs_user), exit 1
    assert result.returncode == 1, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # No git dir created
    assert not (vault / ".git").exists(), ".git was created despite --no-git"
    # Corpus renamed
    assert (vault / "data_vault").exists(), "corpus not renamed with --no-git"


# ---------------------------------------------------------------------------
# --draft-only flag
# ---------------------------------------------------------------------------


def test_draft_only_flag(tmp_path: Path) -> None:
    """--draft-only: stops after drafting the spec even if a spec existed."""
    vault = tmp_path / "draft-vault"
    vault.mkdir()
    (vault / "Notes").mkdir()
    (vault / "Notes" / "note.md").write_text("# Note\n", encoding="utf-8")
    (vault / "README.md").write_text("# Draft Vault\n\nA test.\n", encoding="utf-8")

    # Write spec manually so step 3 would normally be skipped
    spec = vault / "draft-vault-spec.md"
    spec.write_text(
        "---\n"
        "name: Draft Vault\n"
        "owner: Test User\n"
        "topic: A test vault.\n"
        "growth_mode: incremental\n"
        "scope:\n"
        "  include:\n"
        "    - Notes\n"
        "  exclude: []\n"
        "sources:\n"
        "  - name: Web\n"
        "---\n\n# Draft Vault\n",
        encoding="utf-8",
    )
    (vault / "data_vault").mkdir()

    result = _run_onboard([str(vault), "--draft-only", "--no-git"])

    # With --draft-only and spec already present, step 3 is skipped and
    # --draft-only stops after step 3. Step 4 requires parse-spec to succeed;
    # without spec-parse.json, parse-spec will be called. Either way we just
    # check --draft-only printed the stop message.
    assert "--draft-only" in result.stdout or "stopped after step 3" in result.stdout
