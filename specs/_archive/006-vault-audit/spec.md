# Spec 006 — Vault Audit

**Prerequisite:** Spec 005 (Adaptive Sources) must be implemented first.
`vault_audit.py` reads `source_quality_summary()` from `source_manager.py`.

**Status:** shipped(2026-05-13, commit 3fd97a7) — **SHIPPED (early 0.2.x — pre-status-header-convention).** Shipped in the foundational autonomous-pipeline window (`feat(006): vault_audit.py — deterministic validators + source quality report`, commit `3fd97a7`, pyproject `0.2.15`, 2026-05-13); `scripts/vault_audit.py` is live today. Predates the CHANGELOG (which begins at 0.2.18) and the status-header convention.

## Problem Statement

The existing quality tooling is fragmented and deterministic-only:

- `validate_vault.py` — frontmatter field checks
- `check_template_compliance.py` — required section headings
- `check_acronym_links.py` — wikilink acronym coverage
- `vault_health.py` — wikilink resolution, URL health, template version drift

Running these individually gives partial pictures. More importantly, none of
them can answer the questions that matter most for vault quality:

- Are my sources still relevant to this vault's scope, or are they drifting?
- Are notes substantive, or are they filled with placeholder prose?
- Is the vault's information consistent with itself, or are there contradictions?
- Which source is driving the most value, and which are dead weight?

These require judgement, not just pattern matching.

## Proposed Solution

A new `scripts/vault_audit.py` that runs as a single command and produces
one unified report. Two layers:

**Layer 1 — Deterministic (orchestrated, no LLM cost)**
Calls all existing validators and `vault_health.py`. Aggregates their exit
codes and outputs into one structured view.

**Layer 2 — Haiku-assisted quality signals (per category, opt-in)**
Runs lightweight Haiku-based checks that pattern matchers can't do:
- **Source relevance**: for each active source in `sources.db`, evaluate
  whether it is still producing content relevant to `spec.scope.domain`
- **Summary fidelity**: sample N notes per type; check `summary` field
  actually reflects the note body
- **Placeholder detection**: flag notes where `## Current Behaviour` or
  `## Stated Intent` sections contain only template placeholder text
- **Information density**: flag notes that are word-count-passing but
  structurally thin (e.g. 300 words of bullet restating the title)

Haiku checks are batched — one call per category, not per note — to keep
audit cost manageable. A full audit on a 200-note vault should cost < $0.10.

**Output:** `_pipeline/audit-report.md` — one section per check category,
pass/fail grade, list of flagged items with file paths and reasons.
Also exits non-zero if any category fails, so `./vault audit` can be used
as a CI gate.

## Non-Goals

- Replacing `vault_health.py` — stays deterministic and separate (called
  inside the cycle loop; must remain fast and LLM-free)
- Per-note deep review — that's the verifier's job (spec 004, already shipped)
- Auto-fixing issues — audit reports only; maintenance flow (spec 010) does fixes
- Real-time or continuous audit — runs on demand or scheduled, not per-cycle

## Technical Design

### New file: `scripts/vault_audit.py`

```
usage: vault_audit.py <vault_dir> [--full] [--no-llm] [--output PATH]
                      [--sample-size N]

--full          run all checks including LLM tier (default: deterministic only)
--no-llm        skip Haiku checks even if settings enable them
--output PATH   write report to PATH instead of _pipeline/audit-report.md
--sample-size N notes per type sampled for LLM checks (default: 10)
```

Exit codes: `0` = all pass, `1` = one or more categories fail, `2` = error.

### Report structure

```markdown
# Vault Audit — <vault_name> — <timestamp>

## Summary

| Category | Status | Issues |
|----------|--------|--------|
| Wikilinks | ✅ PASS | 0 |
| External URLs | ⚠️ WARN | 2 stale |
| Template compliance | ✅ PASS | 0 |
| Source quality | ❌ FAIL | 1 archived, 2 low-yield |
| Note quality (Haiku) | ⚠️ WARN | 3 placeholder sections |

Overall: WARN

## Wikilinks
…

## Source Quality
(reads from source_manager.source_quality_summary())
…
```

### Haiku check pattern

Each LLM check follows the same pattern:
1. Sample N notes (deterministic sampling — same vault state = same sample)
2. Build a single prompt with all sampled notes inline
3. Call `agent_call.py --stage vault_audit --vault <vault_dir>` with the prompt
4. Parse structured JSON response: `{category, issues: [{path, reason}]}`
5. Write issues to the report section

Prompts are rendered from `templates/prompts/audit-*.md.j2` templates so
they can be customised per vault.

### New skill: `.agents/skills/vault-audit/SKILL.md`

Input contract: list of note excerpts + vault scope.
Output contract: structured JSON with `issues[]` — each with `path` and
`reason`. Never invents paths not in the input. Rejects on structural
ambiguity rather than guessing.

### Settings

```yaml
stages:
  vault_audit:
    enabled: true
    model: haiku          # cheap tier — structural checks only
    timeout_s: 120
    sample_size: 10       # notes per type sampled for LLM checks
    checks:
      source_relevance: true
      summary_fidelity: true
      placeholder_detection: true
      information_density: false   # opt-in — higher false-positive rate
```

## Acceptance Criteria

1. `python scripts/vault_audit.py <vault_dir>` exits 0 on a clean vault,
   1 on violations, 2 on structural error
2. `--no-llm` produces a report identical to running all deterministic
   validators + `vault_health.py` individually, aggregated
3. `--full` adds source quality section using `source_quality_summary()`
   from spec 005; degrades gracefully if `sources.db` absent (skips section)
4. Haiku check batch cost for a 200-note vault is logged and under $0.10
5. Report written to `_pipeline/audit-report.md` unless `--output` overrides
6. `stages.vault_audit.enabled: false` skips LLM checks even when `--full` is passed
7. All existing tests pass; new tests cover each exit-code path and the
   JSON parsing of Haiku responses

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Haiku flags good notes as placeholder | Medium | Low | `--no-llm` default; LLM tier opt-in; sample-based (not all notes) |
| `source_quality_summary()` unavailable (005 not yet run) | Medium | Low | Degrade gracefully — skip source section, log notice |
| Audit runs too slowly for interactive use | Low | Medium | Deterministic tier is fast; Haiku tier batched and bounded by `sample_size` |
