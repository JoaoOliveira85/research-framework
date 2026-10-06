# ADR-0003: Correction directives must be injected into agent prompts

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: correction-loop, spec-019, 0.2.30, cycle-runner, agents

## Context

0.2.29 introduced the SG-006 correction loop: when a quality gate
fails, the framework writes a directive (an explicit "the previous
attempt failed because X \u2014 please fix Y") to
`_pipeline/corrections/cycle-NNN.json` and re-invokes the stage.
The intent was that the second attempt would see the directive and
adjust.

In the user's 0.2.29 trial, the loop ran, the directive was
written correctly, and the cycle aborted with the SAME validation
errors. Forensics:

- The directive file existed and had the right contents.
- `cycle_runner._render_prompt()` was the function that built the
  retry prompt. It performed only a pure substring substitution on
  the template; it did NOT read the corrections directory.
- Therefore the second attempt received an identical prompt to the
  first attempt. The agent had no way of knowing it was a retry.

This was a critical regression: we had built a correction
mechanism but failed to actually deliver the corrections to the
party that needed to act on them. The mechanism was working from
the framework's perspective ("we wrote the directive!") and
failing from the agent's perspective ("I never saw any directive").

A second, related problem: even when injection works, leaving
applied directives in `_pipeline/corrections/` makes future cycles
think the same correction is still pending. We needed a cleanup
discipline as well.

## Decision

Two coupled changes:

1. **`_render_prompt()` reads correction directives.** When invoked
   with `vault_dir` and `cycle_num` arguments, the function checks
   `_pipeline/corrections/cycle-NNN.json` and, if present, prepends
   a formatted Markdown block to the prompt. The block names the
   prior failure and the explicit corrective ask.
2. **Successful retries archive their directive.** When a retry
   passes validation, the cycle runner moves the directive from
   `_pipeline/corrections/cycle-NNN.json` to
   `_pipeline/corrections/applied/cycle-NNN-<timestamp>.json`. The
   archive serves as an audit trail and prevents the directive
   from being re-applied on the next cycle.

The hint text inside the directive is intentionally CONCRETE \u2014
includes JSON examples of the expected shape rather than abstract
descriptions \u2014 because agents read by pattern-matching, not by
parsing.

## Consequences

**Good**:

- The correction loop actually works end-to-end. Agents that
  failed validation get a clearly-marked second chance with the
  specific corrective ask in their prompt.
- The audit trail in `corrections/applied/` makes post-mortems
  trivially possible: every cycle's full correction history is on
  disk.
- The injection is opt-in by call-site (you have to pass
  `vault_dir` + `cycle_num`) so existing tests that exercise the
  initial-render path don't suddenly start seeing directives.

**Trade-offs**:

- `_render_prompt` now has two modes (with and without directive
  injection). Every call site has to choose the right mode. We
  catch this in code review and in integration tests.
- Directives are part of the prompt, so they consume tokens. For
  long-running corrections this could matter; in practice
  directives are <500 tokens.

## Alternatives considered

- **Pass the directive as a separate file the agent must read**.
  Rejected: requires the agent to know about the directive file
  convention. The prompt is already the agent's contract surface
  \u2014 putting the directive there matches how agents already work.
- **Re-render the entire stage prompt from scratch on each retry**.
  Considered. Equivalent in behaviour but more expensive and
  doesn't leave the same audit trail.
- **Leave directives in place after successful retry** (no
  archive). Rejected: next cycle would re-apply a directive that's
  already been satisfied.

## Tests

- `tests/pipeline/test_cycle_runner_directive_injection.py` covers
  the happy path (directive present \u2192 included in retry prompt
  \u2192 retry succeeds \u2192 directive archived).
- `tests/pipeline/test_cycle_runner_directive_injection.py::test_first_attempt_prompt_has_no_directive`
  is the negative-case sanity check.
- `tests/pipeline/test_cycle_runner_scout_correction.py` was
  updated to look for the directive in EITHER `corrections/` (mid-
  retry) or `corrections/applied/` (post-retry).
