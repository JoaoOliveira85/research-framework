---
name: "speckit-taskstoissues"
description: "Convert a spec's tasks.md (task-level granularity) OR spec.md (spec-level granularity) into actionable GitHub issues, with optional milestone + label assignment."
argument-hint: "[--mode spec|task] [--milestone <name>] [--labels <l1,l2,...>] [FEATURE_DIR]"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "github-spec-kit (originally) + research-framework local adaptations (2026-05-27)"
  source: "templates/commands/taskstoissues.md"
user-invocable: true
disable-model-invocation: true
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Argument parsing

Parse `$ARGUMENTS` into:

| Arg | Default | Meaning |
|---|---|---|
| `--mode spec\|task` | `task` | Granularity: one issue per task (default) or one issue per spec. |
| `--milestone <name>` | none | If provided, attach all created issues to this milestone (must already exist). |
| `--labels <l1,l2,...>` | none | If provided, attach these labels to all created issues (comma-separated; labels must exist). |
| `FEATURE_DIR` (positional) | inferred from current spec-kit branch | Override the feature dir. Useful when invoking against a non-current spec. |

**Examples**:

- `/speckit-taskstoissues` — task-mode (default), current feature, no milestone/labels
- `/speckit-taskstoissues --mode spec --milestone "Milestone A — youtube + first feeds-vault cycle" --labels "kind:tier-1-module,priority:critical,epic:wave-2-modules"` — one spec-level issue with Milestone A + 3 labels
- `/speckit-taskstoissues --mode spec --labels "type:spec,epic:post-revival-sweep" specs/030-quality-harness-v3` — spec-mode against an explicit feature dir

## Pre-Execution Checks

**Check for extension hooks (before tasks-to-issues conversion)**:
- Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.before_taskstoissues` key
- If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Pre-Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Pre-Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}

    Wait for the result of the hook command before proceeding to the Outline.
    ```
- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently

## Outline

1. **Parse arguments** (see Argument parsing section above). Validate that `--mode` is either `spec` or `task` (default `task`).

2. **Resolve FEATURE_DIR**:
   - If a positional `FEATURE_DIR` was provided in `$ARGUMENTS`, use it directly (validate that `<FEATURE_DIR>/spec.md` exists).
   - Otherwise, run `.specify/scripts/bash/check-prerequisites.sh --json --paths-only` from repo root and parse `FEATURE_DIR`. (Use `--paths-only` so we don't require `tasks.md` to exist — that's only required in task mode.)
   - In `task` mode, additionally require `<FEATURE_DIR>/tasks.md`. In `spec` mode, require only `<FEATURE_DIR>/spec.md`.

   All paths must be absolute. For single quotes in args like "I'm Groot", use escape syntax: e.g `'I'\''m Groot'` (or double-quote if possible: `"I'm Groot"`).

3. **Confirm the Git remote is GitHub**:

   ```bash
   git config --get remote.origin.url
   ```

   > [!CAUTION]
   > ONLY PROCEED TO NEXT STEPS IF THE REMOTE IS A GITHUB URL.

   > [!CAUTION]
   > UNDER NO CIRCUMSTANCES EVER CREATE ISSUES IN REPOSITORIES THAT DO NOT MATCH THE REMOTE URL.

4. **Validate milestone + labels** (if provided):
   - For `--milestone`, run `gh api repos/{owner}/{repo}/milestones --jq '.[].title'` and confirm an exact-match exists. Bail with an error if it doesn't.
   - For `--labels`, run `gh label list --json name -q '.[].name'` and confirm every label exists. Bail with an error listing missing labels.

5. **Branch by mode**:

### Mode: `task` (default — original behavior)

Parse the task list from `<FEATURE_DIR>/tasks.md`. For each task, create a GitHub issue:

- **Title**: the task heading or its bolded first line
- **Body**: the task's full text + a footer link to the parent spec
- **Labels**: `--labels` arg if provided
- **Milestone**: `--milestone` arg if provided

Use `gh issue create --title "..." --body "..." [--label "..." ...] [--milestone "..."]`. If the GitHub MCP server is available, use it preferentially (cleaner error handling).

### Mode: `spec`

Read `<FEATURE_DIR>/spec.md`. Create ONE issue:

- **Title**: `Spec NNN: <h1 title without leading number>` (e.g. for `specs/030-quality-harness-v3/spec.md` with `# 030 — Quality harness v3`, title would be `Spec 030: Quality harness v3`).
- **Body**: structured template containing:
  - The Spec's Status line (parsed from the frontmatter or `**Status**:` line)
  - A link to the spec file in `../blob/main/<feature-dir>/spec.md`
  - A short Summary (parse the spec's Summary or first paragraph after `# `)
  - An Acceptance criteria stub referencing spec.md
  - A footer with provenance ("*Created by /speckit-taskstoissues on YYYY-MM-DD*").
- **Labels**: `--labels` arg if provided
- **Milestone**: `--milestone` arg if provided

Suggested body template (use markdown):

```markdown
**Status**: <parsed from spec.md>
**Spec**: [`<feature-dir>/spec.md`](../blob/main/<feature-dir>/spec.md)

## Summary

<first paragraph after the H1, or the "Summary" section if present>

## Acceptance criteria

See spec.md for the full sketch. Pre-clarify, criteria are deliberately a rough draft — promote with `/speckit.clarify`.

---

*Created by `/speckit-taskstoissues --mode spec` on <ISO date>.*
```

6. **Report**: after creating issues, print:
   - Number created and the issue URLs
   - Any labels/milestones applied
   - Reminder to pin the master tracker (#68 in this repo) if relevant

## Post-Execution Checks

**Check for extension hooks (after tasks-to-issues conversion)**:
Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.after_taskstoissues` key
- If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    ```
- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently

## Conventions (research-framework local)

- **Per-spec issues** ([conventions added 2026-05-27 during sprint setup](../../../docs/ROADMAP.md)): one issue per spec, labelled with one epic (`epic:revival-sprint` / `epic:wave-2-modules` / `epic:post-revival-sweep` / `epic:horizon-2` / `epic:horizon-3` / `epic:future-stubs`), one `type:` (most are `type:spec`), one `priority:` (`critical`/`high`/`medium`/`low`), and optional `kind:` labels.
- **Wave-2 module issues** sit under `epic:wave-2-modules` + `kind:tier-1-module` and are assigned to one of the three milestones (A/B/C).
- **Master tracking issue** (`🎯 Feeds-Vault Revival Sprint — master tracker`, #68 at time of writing) is the human-facing index; it links to every sub-issue and mirrors `docs/ROADMAP.md`. Update it when you add new sub-issues.
- **Pin operation**: GitHub's REST pin endpoint requires `repo:admin` scope; if `gh api -X PUT repos/{owner}/{repo}/issues/{n}/pin` returns 404, pin manually from the web UI (Issue page → "Pin issue" in the right sidebar).

## Lifecycle reminders (run AFTER this skill)

This skill creates issues but does not maintain them. Drift discipline lives in [`CLAUDE.md` "GitHub issue + milestone hygiene"](../../../CLAUDE.md). The two stages where the human/agent MUST come back and touch issues:

1. **After `/speckit.clarify`** — if scope shifted, re-label the spec's issue (`gh issue edit N --remove-label priority:medium --add-label priority:high`) and adjust milestone assignment if the spec became Wave-2-gating.

2. **After implementation ships** — the merging PR body MUST contain `Closes #<spec-issue>` so the spec's tracking issue auto-closes on merge. After merge, verify with `gh issue view N --json state -q '.state'` (expect `CLOSED`). Also verify the master tracker (#68) checkbox flipped; if not, edit #68 to tick the box manually.

3. **When a spec moves between epics** (rare but happens) — re-run this skill against the spec with the new `--labels` arg, then delete the stale issue:
   ```bash
   gh issue close <old-issue> -c "re-categorised; see #<new-issue>"
   ```

The full per-stage discipline is in `CLAUDE.md`'s "Per-spec-kit-stage doc-update checklist" — every stage has `GitHub Issue` bullets alongside the `docs/ROADMAP.md` bullets.
