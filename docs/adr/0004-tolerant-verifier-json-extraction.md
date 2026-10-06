# ADR-0004: Verifier output parsing must tolerate non-strict JSON

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: verifier, agents, output-parsing, 0.2.31

## Context

The verifier stage runs per-note quality checks by sending the note
to an agent and parsing back a JSON verdict. The contract (declared
in `.agents/skills/verifier/SKILL.md`) is that the agent returns
`{verdict: "accept" | "reject", violations: [...], suggested_fix: ...}`.

In 0.2.30 we deployed this with strict `json.loads()` parsing and a
bare except that defaulted to `status: "pending"` on parse failure.
The user's reference-vault-0.2.30 ran 6 cycles with 68 substantive notes
and every single verifier verdict came back as `pending` \u2014 silent,
no errors logged. The cycle's stub-free-exit Principle VIII guard
fired on every cycle because pending notes count as stubs.

Root cause was a two-line interaction:

1. The prompt sent to the agent (`agent_call.py` via the verifier)
   was the BARE note content. No instruction. The agent had no idea
   it was being asked to verify anything; it had no schema in its
   prompt context. Claude Code auto-loads `SKILL.md` from
   `.agents/skills/` at session start; codex does not.
2. The codex agent's natural response was a narrative summary of
   the note. Narrative text never parses as JSON, so the bare
   except defaulted to `pending` every single time \u2014 no log, no
   warning, no signal.

This was the worst kind of bug: the framework's introspection
("how many notes did the verifier accept?") was permanently broken
on the most common runtime, and the symptom (stub-flood) misdirected
the investigation toward "the agents aren't writing enough."

## Decision

Two complementary fixes in `src/research_vault/pipeline/verifier.py`:

1. **Inline the verifier contract in the prompt.** New helper
   `_build_verifier_prompt(note_content)` wraps the note in a short
   instruction block that names the verifier skill, restates the
   JSON output schema, and instructs the agent to default to
   `reject` on uncertainty. The block points at `SKILL.md` for the
   full rules but restates the SCHEMA inline because the framework's
   parser depends on it.
2. **Tolerantly extract JSON from the agent's response.** New
   helper `_extract_json_blob(text)` tries, in order:
   - Strict `json.loads()` of the whole text (covers compliant
     agents).
   - Code-fenced JSON via the `` ```json...``` `` and `` ```...``` ``
     patterns (the codex/GPT-4 conventional shape; first valid
     fence wins).
   - Balanced-braces walk over the raw text to find embedded
     `{...}` blocks (covers narrative-wrapped JSON).
   Returns the parsed dict or `None`. Top-level arrays or non-object
   scalars correctly return `None` (schema mismatch) so the caller
   still defaults to `pending` deliberately.

The combination is necessary. The prompt wrapper turns most agents
into compliant ones; the tolerant extractor catches the rest.

## Consequences

**Good**:

- Verifier verdicts now populate correctly across both Claude Code
  and codex runtimes.
- The "65 stubs" misclassification disappears \u2014 stub-free-exit
  becomes meaningful again.
- The extractor pattern is reusable: any future agent stage that
  needs JSON output can call `_extract_json_blob` instead of
  reinventing the parse path.

**Trade-offs**:

- Prompt length grows by ~30 lines per verifier call. We accept
  this; the cost (a few hundred extra tokens per note) is dwarfed
  by the benefit (verifier actually works).
- The tolerant extractor MAY accept JSON the framework didn't
  expect (e.g. an extra field). That's intentional \u2014 we want to
  be liberal in what we accept and strict in what the verifier's
  consumers do with the parsed shape.

## Alternatives considered

- **Force codex to load SKILL.md at startup.** Looked at; runtime-
  specific and brittle. The prompt wrapper is runtime-agnostic.
- **Switch the agent contract from JSON to a single-line "ACCEPT |
  REJECT" verdict.** Rejected: we lose violation detail and
  suggested-fix metadata. The downstream `validate_vault.py` uses
  the violations to populate the run report.
- **Just log a warning when parse fails.** Rejected: addresses
  visibility but not the actual bug. The verifier still wouldn't
  work; we'd just KNOW it didn't work.

## Tests

`tests/pipeline/test_verifier_json_extraction.py` covers 13 cases
including strict parse, code-fenced (with/without language tag),
narrative-embedded, nested braces, malformed-then-valid fallback,
top-level array (must reject), and edge cases (empty input,
whitespace-only). All GREEN at the time of this ADR.
