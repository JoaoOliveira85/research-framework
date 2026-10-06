# Spec 007 — Autonomous Vault Operation Settings

**Status:** shipped(2026-05-13, commit 102bdb5) — **SHIPPED (early 0.2.x — pre-status-header-convention).** Shipped in the foundational autonomous-pipeline window (`feat(007): scaffold writes .claude/settings.json; CLAUDE.md gets autonomous-op section`, commit `102bdb5`, pyproject `0.2.15`, 2026-05-13; the broader autonomous-pipeline ship is recorded in `22e57da` "ship 0.2.17 → 0.2.27"). Predates the CHANGELOG (which begins at 0.2.18) and the status-header convention.

## Problem Statement

Every operation a Claude Code agent performs inside a generated vault triggers
permission prompts: reading files, running scripts, fetching URLs, calling the
`claude` CLI. This is appropriate for a first-run safety net but becomes an
obstacle for autonomous use — scheduled research cycles, iOS Shortcut triggers,
or any non-interactive workflow.

The goal is for vaults to run autonomously by default, with human confirmation
reserved for the small set of genuinely irreversible or expensive actions.

## Proposed Solution

`scaffold.py` writes a `.claude/settings.json` into every generated vault at
generation time. This file pre-authorises all normal operational tool calls
using Claude Code's `allowedTools` / `bashAllowlist` settings.

The `CLAUDE.md` rendered into the vault is also updated with an "Autonomous
operation" section that instructs the agent on when to proceed vs. when to
ask.

## Non-Goals

- Modifying the global `~/.claude/settings.json` — vault settings are
  vault-local only
- Pre-authorising destructive operations (note deletion, git force-push,
  bulk overwrites, spending above budget) — these always require confirmation
- Pre-authorising network access outside the vault context (e.g. posting to
  Slack, creating Jira tickets) — these stay gated

## Technical Design

### `.claude/settings.json` template

Written by `scaffold.py` to `<vault>/.claude/settings.json`. The content
is rendered from a new Jinja2 template `templates/claude-settings.json.j2`
so vault-specific values (vault root path, budget cap) can be interpolated.

```json
{
  "permissions": {
    "allow": [
      "Bash(python scripts/*.py:*)",
      "Bash(python -m research_vault.*:*)",
      "Bash(./vault *)",
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(find . *)",
      "Bash(ls *)",
      "Bash(cat *)",
      "Bash(grep *)",
      "WebFetch(*)",
      "WebSearch(*)"
    ],
    "deny": [
      "Bash(git push *)",
      "Bash(git reset --hard *)",
      "Bash(rm -rf *)",
      "Bash(git branch -D *)"
    ]
  }
}
```

`WebFetch(*)` and `WebSearch(*)` are broadly permissive — discovered sources
will have unknown domains and a fixed allowlist would block them (see spec 005).

### CLAUDE.md "Autonomous operation" section

Rendered into the vault's `CLAUDE.md` at generation time:

```markdown
## Autonomous Operation

This vault is configured for autonomous operation. Proceed without asking for
confirmation when:
- Running research cycles, validation, health checks, or audit
- Reading or writing files under `data_vault/`, `_pipeline/`, `raw_data/`
- Fetching URLs for source health checks or raw capture
- Committing changes to git (with appropriate commit messages)

Always ask before:
- Deleting any note from `data_vault/`
- Pushing to a git remote
- Spending more than `{{ spec.budget.max_usd }}` USD in a single session
- Making changes outside the vault root directory
```

### Changes to `scaffold.py`

1. Create `<vault>/.claude/` directory
2. Render `templates/claude-settings.json.j2` → `<vault>/.claude/settings.json`
3. If the vault's `settings.yaml` uses `runtime: codex`, also render
   `templates/codex-settings.json.j2` → `<vault>/.codex/settings.json`
   (Codex CLI equivalent — format to be determined from Codex CLI docs
   at implementation time; mirrors the same allow/deny intent)
4. The CLAUDE.md template already exists; add the autonomous-operation section
   to `templates/CLAUDE.md.j2`

### Changes to `_assets.py` / wheel bundling

`templates/claude-settings.json.j2` (and the Codex equivalent) must be
included in the wheel's `_data/templates/` bundle (same mechanism as other
templates).

### Settings

No new `settings.yaml` keys — this feature is always-on at scaffold time.
Users who want stricter defaults can edit `.claude/settings.json` after
generation.

## Acceptance Criteria

1. `research-vault generate --spec <spec> --output <vault>` creates
   `<vault>/.claude/settings.json` with the allow/deny lists above
2. `WebFetch` and `WebSearch` are in the allow list
3. `git push` and `rm -rf` are in the deny list
4. The vault's `CLAUDE.md` contains the "Autonomous Operation" section with
   the correct budget cap interpolated from the spec
5. Running `python scripts/validate_vault.py <vault>` from inside the vault
   in a Claude Code session does not trigger a permission prompt
6. The `.claude/settings.json` is included in the built wheel and bundle
7. All existing scaffold tests pass; new test asserts the settings file exists
   and contains `WebFetch(*)`

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `WebFetch(*)` is too broad — agent fetches unintended URLs | Low | Low | Scout and DFS prompts instruct agents to only fetch sources in `sources.db`; this is a guardrail, not a permission bypass |
| Settings format changes in a future Claude Code version | Medium | Medium | Template is version-pinned in comments; update during normal maintenance |
| User overrides deny list and runs a destructive command | Low | High | CLAUDE.md autonomous-op section makes the intent explicit; this is a soft guardrail |
