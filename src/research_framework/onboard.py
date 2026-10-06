"""Vault onboarding orchestrator.

Drives the uniform 5-step flow that adopts an existing vault under the
research-framework framework:

  1. git init + seed commit
  2. corpus folder detection / rename
  3. draft spec from prose docs (stops for user review)
  4. parse-spec → _pipeline/spec-parse.json

Usage::

    from research_framework.onboard import run_onboard
    exit_code = run_onboard(Path("/path/to/vault"))
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = ["run_onboard", "StepResult"]

# Directories that are never candidates for the corpus folder.
_NON_CORPUS_DIRS: frozenset[str] = frozenset(
    {
        ".claude",
        ".cursor",
        ".git",
        "_pipeline",
        "_templates",
        "raw_data",
        "scripts",
        "tests",
        "docs",
        "__pycache__",
        ".pytest_cache",
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    status: Literal["done", "skipped", "needs_user", "aborted"]
    message: str
    equivalent_command: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_step(n: int, total: int, description: str) -> None:
    print(f"\n[onboard {n}/{total}] {description} …")


def _print_cmd(cmd: str) -> None:
    print(f"  $ {cmd}")


def _print_result(msg: str) -> None:
    print(f"  → {msg}")


def _aborted(step: int, result: StepResult, note: str = "") -> int:
    """Say on stderr why onboarding aborted, and return 2 (spec 077 FR-017).

    The reason used to go to stdout only, which FR-017 does not count, so the
    CLI appended its "framework bug" apology to an abort it had explained.
    """
    print(f"  → {result.message}", file=sys.stderr)
    print(f"\n[onboard] Aborted at step {step}.{note}", file=sys.stderr)
    return 2


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Thin wrapper — same signature as vault_git._run."""
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _git_available() -> bool:
    try:
        r = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _count_staged(vault: Path) -> int:
    """Return the number of staged files after a 'git add -A'."""
    r = _run(["git", "diff", "--cached", "--name-only"], vault)
    if r.returncode != 0:
        return 0
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return len(lines)


# ---------------------------------------------------------------------------
# Step 1 — git init + seed commit
# ---------------------------------------------------------------------------


def _step_git_init(vault: Path, *, no_git: bool) -> StepResult:
    if no_git:
        return StepResult(
            status="skipped",
            message="--no-git: git operations suppressed",
            equivalent_command="",
        )

    if not _git_available():
        return StepResult(
            status="skipped",
            message="git not found on PATH — skipping",
            equivalent_command="",
        )

    git_dir = vault / ".git"
    if git_dir.exists():
        return StepResult(
            status="skipped",
            message="git repo already initialised   ✓",
            equivalent_command="",
        )

    # Init
    cmd_init = f"git -C {vault} init -q -b main"
    _print_cmd(cmd_init)
    r = _run(["git", "init", "-q", "-b", "main"], vault)
    if r.returncode != 0:
        # Some older git versions don't support -b; fall back
        _run(["git", "init", "-q"], vault)

    # Configure identity only if not already set globally
    identity_cmd = []
    check_email = _run(["git", "config", "--global", "user.email"], vault)
    if check_email.returncode != 0 or not check_email.stdout.strip():
        identity_cmd += [
            f"git -C {vault} config user.email research-framework@local",
            f"git -C {vault} config user.name research-framework",
        ]
        _run(["git", "config", "user.email", "research-framework@local"], vault)
        _run(["git", "config", "user.name", "research-framework"], vault)
        for c in identity_cmd:
            _print_cmd(c)

    # Stage + commit
    cmd_add = f"git -C {vault} add -A"
    cmd_commit = f'git -C {vault} commit -q -m "vault: pre-onboarding initial state"'
    _print_cmd(cmd_add)
    _run(["git", "add", "-A"], vault)
    n_staged = _count_staged(vault)

    _print_cmd(cmd_commit)
    r_commit = _run(
        ["git", "commit", "-q", "-m", "vault: pre-onboarding initial state"], vault
    )
    if r_commit.returncode != 0:
        # Nothing to commit is okay (empty vault)
        if "nothing to commit" in (r_commit.stdout + r_commit.stderr):
            return StepResult(
                status="done",
                message="nothing to commit — empty vault, git repo initialised",
                equivalent_command=cmd_init,
            )
        return StepResult(
            status="aborted",
            message=f"git commit failed: {r_commit.stderr.strip()}",
            equivalent_command=cmd_commit,
        )

    return StepResult(
        status="done",
        message=f"committed {n_staged:,} files",
        equivalent_command=cmd_init,
    )


# ---------------------------------------------------------------------------
# Step 2 — corpus folder detection
# ---------------------------------------------------------------------------


def _step_corpus(vault: Path, *, no_git: bool) -> StepResult:
    data_vault = vault / "data_vault"
    if data_vault.exists():
        return StepResult(
            status="skipped",
            message="corpus folder is data_vault/   ✓",
            equivalent_command="",
        )

    # Find candidate directories
    candidates = [
        d
        for d in vault.iterdir()
        if d.is_dir() and d.name not in _NON_CORPUS_DIRS and not d.name.startswith(".")
    ]

    if len(candidates) == 0:
        msg = (
            "✗ no corpus directory found, vault must have one folder of notes; "
            "aborting."
        )
        print(f"  {msg}")
        return StepResult(
            status="aborted",
            message=msg,
            equivalent_command="",
        )

    if len(candidates) > 1:
        names = ", ".join(f'"{c.name}/"' for c in sorted(candidates))
        msg = (
            "✗ Multiple candidate corpus directories found:\n"
            + "\n".join(f'    - "{c.name}/"' for c in sorted(candidates))
            + "\n  Refusing to choose automatically. Decide manually:\n"
            + f"    git -C {vault} mv <chosen> data_vault\n"
            + "  then re-run `research_framework onboard`."
        )
        print(f"  {msg}")
        return StepResult(
            status="aborted",
            message=f"multiple candidate corpus directories found: {names}; refusing to choose automatically. Resolve manually then re-run.",
            equivalent_command="",
        )

    # Exactly one candidate
    candidate = candidates[0]
    print(f'  Found candidate corpus directory: "{candidate.name}/"')
    print(f'  Renaming "{candidate.name}/" → "data_vault/"')

    if no_git:
        # Rename without git
        candidate.rename(vault / "data_vault")
        return StepResult(
            status="done",
            message=f'renamed "{candidate.name}" → data_vault/ (no-git mode)',
            equivalent_command=f"mv {candidate} {vault / 'data_vault'}",
        )

    cmd_mv = f'git -C {vault} mv "{candidate.name}" data_vault'
    cmd_commit = f'git -C {vault} commit -q -m "vault: rename corpus to data_vault/"'
    _print_cmd(cmd_mv)
    r_mv = _run(["git", "mv", candidate.name, "data_vault"], vault)
    if r_mv.returncode != 0:
        # Git mv might fail if the folder isn't tracked yet; fall back to plain rename
        candidate.rename(vault / "data_vault")
        _run(["git", "add", "-A"], vault)

    _print_cmd(cmd_commit)
    r_commit = _run(
        ["git", "commit", "-q", "-m", "vault: rename corpus to data_vault/"], vault
    )
    if r_commit.returncode != 0 and "nothing to commit" not in (
        r_commit.stdout + r_commit.stderr
    ):
        return StepResult(
            status="aborted",
            message=f"git commit failed: {r_commit.stderr.strip()}",
            equivalent_command=cmd_commit,
        )

    return StepResult(
        status="done",
        message="renamed and committed",
        equivalent_command=cmd_mv,
    )


# ---------------------------------------------------------------------------
# Step 3 — draft spec
# ---------------------------------------------------------------------------

_TODO = (
    "# TODO: fill in (see specs/001-research-framework-implementation or set manually)"
)


def _extract_name(readme_text: str | None, vault: Path) -> str:
    if readme_text:
        for line in readme_text.splitlines():
            m = re.match(r"^#\s+(.+)", line.strip())
            if m:
                return m.group(1).strip()
    # Title-case the directory name
    return vault.name.replace("-", " ").replace("_", " ").title()


def _extract_owner(texts: list[str]) -> str:
    for text in texts:
        for line in text.splitlines():
            m = re.search(r"\*?\*?Owner\*?\*?:\s*(.+)", line, re.IGNORECASE)
            if m:
                owner = m.group(1).strip().lstrip("*").rstrip("*").strip()
                if owner:
                    return owner
    return os.environ.get("USER", _TODO)


def _extract_topic(texts: list[str]) -> str:
    """First paragraph under Purpose / What This Vault Covers / first README para."""
    section_re = re.compile(
        r"##\s+(Purpose|What This Vault Covers|Overview|About)\s*$",
        re.IGNORECASE,
    )
    for text in texts:
        lines = text.splitlines()
        in_section = False
        buffer: list[str] = []
        for line in lines:
            if section_re.match(line.strip()):
                in_section = True
                buffer = []
                continue
            if in_section:
                stripped = line.strip()
                if stripped.startswith("#"):
                    break
                if stripped:
                    buffer.append(stripped)
                elif buffer:
                    break
        if buffer:
            return " ".join(buffer)

    # Fall back: first non-heading paragraph of any text
    for text in texts:
        lines = text.splitlines()
        buffer = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("---"):
                continue
            if stripped:
                buffer.append(stripped)
            elif buffer:
                break
        if buffer:
            return " ".join(buffer)[:300]

    return _TODO


def _extract_scope_include(vault: Path) -> list[str]:
    corpus = vault / "data_vault"
    if not corpus.exists():
        return []
    return sorted(
        d.name for d in corpus.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def _extract_scope_exclude(texts: list[str]) -> list[str]:
    section_re = re.compile(
        r"##\s+(Constraints|Out of Scope|What This Vault Does NOT Cover)\s*$",
        re.IGNORECASE,
    )
    for text in texts:
        lines = text.splitlines()
        in_section = False
        items: list[str] = []
        for line in lines:
            if section_re.match(line.strip()):
                in_section = True
                items = []
                continue
            if in_section:
                stripped = line.strip()
                if stripped.startswith("#"):
                    break
                m = re.match(r"^[-*]\s+(.+)", stripped)
                if m:
                    items.append(m.group(1).strip())
        if items:
            return items
    return []


def _extract_sources(texts: list[str]) -> list[str]:
    section_re = re.compile(r"##\s+(Sources|Data Sources)\s*$", re.IGNORECASE)
    for text in texts:
        lines = text.splitlines()
        in_section = False
        items: list[str] = []
        for line in lines:
            if section_re.match(line.strip()):
                in_section = True
                items = []
                continue
            if in_section:
                stripped = line.strip()
                if stripped.startswith("#"):
                    break
                m = re.match(r"^[-*]\s+(.+)", stripped)
                if m:
                    items.append(m.group(1).strip())
        if items:
            return items
    return []


def _draft_spec_content(vault: Path) -> str:
    """Produce YAML frontmatter + body for the draft spec file."""
    # Read prose docs
    prose_files = ["CLAUDE.md", "AGENTS.md", "README.md"]
    texts: list[str] = []
    readme_text: str | None = None
    files_read: list[str] = []
    for fname in prose_files:
        p = vault / fname
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            texts.append(content)
            if fname == "README.md":
                readme_text = content
            size_kb = p.stat().st_size / 1024
            files_read.append(f"{fname} ({size_kb:.0f} KB)")

    if files_read:
        print(f"  Read {', '.join(files_read)}.")

    name = _extract_name(readme_text, vault)
    owner = _extract_owner(texts)
    topic = _extract_topic(texts)
    scope_include = _extract_scope_include(vault)
    scope_exclude = _extract_scope_exclude(texts)
    sources = _extract_sources(texts)

    print("  Inferred:")
    print(f"    name:  {name!r}")
    print(f"    owner: {owner!r}")
    print(f"    topic: {topic[:60]!r}{'...' if len(topic) > 60 else ''}")

    # Build YAML frontmatter
    def _yaml_str(s: str) -> str:
        # Simple quoting: use double-quoted form if special chars present
        if any(
            c in s
            for c in (
                ":",
                "#",
                "[",
                "]",
                "{",
                "}",
                "&",
                "*",
                "?",
                "|",
                "-",
                "<",
                ">",
                "=",
                "!",
                "%",
                "@",
                "`",
                "\n",
                '"',
                "'",
            )
        ):
            escaped = s.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return s

    include_lines = "\n".join(f"    - {_yaml_str(x)}" for x in scope_include)
    exclude_lines = "\n".join(f"    - {_yaml_str(x)}" for x in scope_exclude)
    source_lines = "\n".join(f"  - name: {_yaml_str(x)}" for x in sources)

    if not include_lines:
        include_lines = f"    - {_TODO}"
    if not exclude_lines:
        exclude_lines = f"    - {_TODO}"
    if not source_lines:
        source_lines = "  - name: Web"

    frontmatter = f"""\
---
name: {_yaml_str(name)}
owner: {_yaml_str(owner)}
topic: {_yaml_str(topic)}
goal: "{_TODO}"
growth_mode: incremental
scope:
  include:
{include_lines}
  exclude:
{exclude_lines}
sources:
{source_lines}
---

# {name}

*Draft spec generated by `research_framework onboard`. Edit the YAML frontmatter
above, then re-run `research_framework onboard {vault}` to continue.*

## Purpose

{topic}

## Scope

<!-- Fill in what this vault covers and what it does not. -->
"""
    return frontmatter


def _find_existing_spec(vault: Path) -> Path | None:
    """Return the first spec file found in the vault, or None."""
    # Canonical name first, then glob
    canonical = vault / f"{vault.name}-spec.md"
    if canonical.exists():
        return canonical
    for p in sorted(vault.glob("*-spec.md")):
        return p
    research = vault / "research.spec.md"
    if research.exists():
        return research
    return None


def _step_draft_spec(vault: Path) -> StepResult:
    existing = _find_existing_spec(vault)
    if existing is not None:
        return StepResult(
            status="skipped",
            message=f"research spec already at {existing.relative_to(vault)}   ✓",
            equivalent_command="",
        )

    spec_path = vault / f"{vault.name}-spec.md"
    content = _draft_spec_content(vault)
    spec_path.write_text(content, encoding="utf-8")

    print(f"\n  Wrote draft spec: {spec_path}")
    print()
    print("  REVIEW REQUIRED — please open and edit this file:")
    print(f"    $EDITOR {spec_path}")
    print()
    print("  When done, re-run:")
    print(f"    research_framework onboard {vault}")

    return StepResult(
        status="needs_user",
        message=f"wrote draft spec {spec_path}; awaiting user review",
        equivalent_command=f"$EDITOR {spec_path}",
    )


# ---------------------------------------------------------------------------
# Step 4 — parse-spec
# ---------------------------------------------------------------------------


def _step_parse_spec(vault: Path) -> StepResult:
    spec_parse_json = vault / "_pipeline" / "spec-parse.json"
    spec_file = _find_existing_spec(vault)

    if spec_file is None:
        return StepResult(
            status="aborted",
            message="no spec file found — cannot parse-spec",
            equivalent_command="",
        )

    # Skip if spec-parse.json is present and newer than the spec
    if spec_parse_json.exists():
        spec_mtime = spec_file.stat().st_mtime
        json_mtime = spec_parse_json.stat().st_mtime
        if json_mtime >= spec_mtime:
            return StepResult(
                status="skipped",
                message="spec-parse.json present and current   ✓",
                equivalent_command="",
            )
        print("  → mtime is more recent than spec-parse.json — re-parsing.")

    cmd = f"research_framework parse-spec {vault} {spec_file.name}"
    _print_cmd(cmd)

    # Call the parse-spec logic via subprocess (avoids circular imports and
    # matches what the user would run by hand)
    env = dict(os.environ)
    src_dir = Path(__file__).resolve().parent.parent
    env["PYTHONPATH"] = str(src_dir)

    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework",
            "parse-spec",
            str(vault),
            str(spec_file),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()
        return StepResult(
            status="aborted",
            message=f"parse-spec failed: {err}",
            equivalent_command=cmd,
        )

    # Print what parse-spec wrote
    for line in (r.stdout or "").splitlines():
        print(f"  {line}")

    return StepResult(
        status="done",
        message=f"wrote {spec_parse_json.relative_to(vault)}",
        equivalent_command=cmd,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_onboard(
    vault_path: Path,
    *,
    draft_only: bool = False,
    no_git: bool = False,
) -> int:
    """Run the 4-step onboarding flow.

    Returns an exit code:
      0 — all steps done (or skipped) successfully
      1 — stopped at step 3 awaiting user spec review (normal, not an error)
      2 — aborted due to an unrecoverable condition
    """
    vault = vault_path.resolve()
    if not vault.exists() or not vault.is_dir():
        print(f"error: not a directory: {vault}", file=sys.stderr)
        return 2

    total = 4

    # Step 1 — git init
    _print_step(1, total, f"init git repo in {vault}")
    s1 = _step_git_init(vault, no_git=no_git)
    if s1.status == "aborted":
        return _aborted(1, s1)
    _print_result(s1.message)

    # Step 2 — corpus folder
    _print_step(2, total, "check corpus folder")
    s2 = _step_corpus(vault, no_git=no_git)
    if s2.status == "aborted":
        return _aborted(2, s2, " The git seed commit (step 1) is preserved.")
    _print_result(s2.message)

    # Step 3 — draft spec
    _print_step(3, total, "draft research spec from prose docs")
    s3 = _step_draft_spec(vault)
    if s3.status == "needs_user":
        print(
            "\n[onboard] Stopped at step 3 — waiting for spec review.", file=sys.stderr
        )
        return 1
    if s3.status == "aborted":
        return _aborted(3, s3)
    _print_result(s3.message)

    if draft_only:
        print("\n[onboard] --draft-only: stopped after step 3.")
        return 0

    # Step 4 — parse-spec
    _print_step(4, total, "parse spec into _pipeline/spec-parse.json")
    s4 = _step_parse_spec(vault)
    if s4.status == "aborted":
        return _aborted(4, s4)
    _print_result(s4.message)

    print("\n[onboard] Done. Vault is ready.")
    print()
    print("Next steps:")
    print("  ./vault research        # run a research cycle")
    print("  ./vault update          # upgrade the framework (pip + install.sh)")
    print()
    print("Or refine the spec first:")
    spec = _find_existing_spec(vault)
    if spec:
        print(f"  $EDITOR {spec}")
        print(f"  research_framework onboard {vault}   # re-runs from step 4")
    return 0
