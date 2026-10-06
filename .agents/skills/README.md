# research-framework skills

Each subdirectory here is a *skill*: a structured prompt + contract that the
orchestrator (or a slash command, or a maintainer's subagent) invokes against
an LLM. Skill files keep prompts out of Python source and make every agent
interaction reproducible and auditable.

Two guards keep this directory honest: `docs/prompts/README.md` (generated
by `scripts/render_prompt_corpus.py`) records every skill file's sha256 in
its "Recorded, not copied" table, so a prompt cannot change without the
corpus table changing with it; and `scripts/guards/check_agent_asset_references.py`
(in the guard battery) fails when code or a template names a skill or agent
asset that does not exist.

## File shape

Every pipeline skill lives at `<name>/SKILL.md` with this structure:

```markdown
---
name: <skill-name>              # matches directory name
description: <one-line>
default_executor:               # default stage executor; spec can override
  runtime: claude
  model: sonnet
input:                          # JSON-ish schema of what the caller passes
  field_a: str
output:                         # JSON-ish schema of what the skill returns
  verdict: str
---

# Role

<one paragraph — what the agent IS>

# Task

<step-by-step instructions>

# Constraints

<what the agent MUST and MUST NOT do>

# Output format

<exact format; usually a JSON fence or a short markdown block>

# Examples

<at least one input/output example>
```

The five `speckit-git-*` skills are spec-kit tooling (frontmatter is `name`
+ `description` only); they are never dispatched by the orchestrator.

## Inventory

26 directories. "Where it runs": **generator** = at spec/scaffold time;
**vault** = inside a research cycle or a vault slash command; **maintainer**
= against this repo, by a subagent, never inside a vault.

| Skill | Where it runs | Purpose |
|-------|---------------|---------|
| `idea-refiner` | generator | Brainstorm with a user who doesn't yet know what to research; produce seed notes for `vault-spec`. |
| `vault-spec` | generator | Guide the user (technical or not) through writing `research.spec.md`. |
| `install-wizard` | generator | Run the interactive part of `install.sh` after `vault-spec` has produced a spec; complete and confirm it before scaffolding. |
| `default-update-spec` | vault | On a vault update with no user-supplied spec, validate the implicit update spec. |
| `scout` | vault | BFS scouting pass over the enumerated data sources; emits scout-report v2. |
| `topic-propose` | vault | Scope-bounded tangent proposer: given this cycle's touched notes, propose adjacent topics inside the spec's bounds. |
| `topic-classifier` | vault | Map a scouted topic onto the vault's configured `note_types` and a complexity. |
| `source-relevance` | vault | Binary related / unrelated gate for a proposed source. |
| `dfs-prompt-gen` | vault | Turn a scout-report v2 plus vault state into the DFS research prompt. |
| `research-plan-narrator` | vault | Narrate a read-only excerpt of the deterministic research plan (spec 017). |
| `note-writer` | vault | Write vault notes for an orchestrator-assigned `batch_topics` list. |
| `note-tagger` | vault | Assign tags and populate `related` on a drafted note. |
| `verifier` | vault | Independent verifier: reject a note, `/ask` answer or `/write` output that violates the citation / quality bar. |
| `cycle-report` | vault | Write the per-cycle analysis into `_pipeline/cycles/cycle-<N>-report.md`. |
| `final-report` | vault | End-of-run synthesis into `_pipeline/final-report.md`. |
| `ask-answer` | vault | Backend of the `/ask` slash command: a vault-grounded answer with two-tier citations. |
| `doc-planner` | vault | Plan a `/write` document: section outline + the vault notes each section draws on. |
| `doc-writer` | vault | Execute a `doc-planner` plan into `output/`, vault-grounded (the `./vault write` shim verb that would drive it does not ship — spec 077 D2). |
| `model-router` | vault | Decide at call time whether to upgrade a stage's executor. |
| `test-designer` | maintainer | Independent test designer: reads a spec's `spec.md` + `plan.md` + `tasks.md` and enriches `tasks.md` with `### Testing Requirements` (ADR-0010). |
| `foreman` | maintainer | Independent code-review agent that runs after the implementer — the Arm B review of ADR-0010. |
| `speckit-git-initialize` | maintainer (spec-kit) | Initialize a git repository with an initial commit. |
| `speckit-git-feature` | maintainer (spec-kit) | Create a feature branch with sequential or timestamp numbering. |
| `speckit-git-validate` | maintainer (spec-kit) | Validate that the current branch follows the feature-branch naming convention. |
| `speckit-git-commit` | maintainer (spec-kit) | Auto-commit changes after a spec-kit command completes. |
| `speckit-git-remote` | maintainer (spec-kit) | Detect the git remote URL for GitHub integration. |

Adding a skill means adding a row here and re-running
`scripts/render_prompt_corpus.py` so the corpus table carries its hash; the
guard battery will tell you if you forget the second half.
