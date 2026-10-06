# ADR-0001: Adopt ADRs for architectural decisions

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: process, documentation, retrospective

## Context

Between 0.2.20 and 0.2.31 we shipped a string of seam-bug releases
that all had a common shape: a fix landed for a real problem, the
problem returned six weeks later under a slightly different name,
and the second "fix" reintroduced the original bug. Specific
instances:

- The `BatchResult` serialization fix in 0.2.21 was effectively
  reverted in 0.2.24 by a refactor that didn't know why the
  original shape existed.
- The TTY/line-buffering workaround in 0.2.22 was "cleaned up" in
  0.2.25 and caused the same crash on a different runtime.
- The budget field aliasing in 0.2.23 was forgotten by the time
  0.2.28's spec-019 work touched the same code path.

Every one of these losses happened because the WHY of the
decision lived only in a commit message that nobody re-read. The
in-code comments captured the WHAT but not the WHY \u2014 they couldn't,
because the explanations were paragraphs long.

The user repeatedly flagged this pattern. After the 0.2.30 audit
the user explicitly asked: "we have to update all of our docs
(including architecture, readme, adrs, etc) to reflect all of the
lessons learned so far so we don't lose all of this knowledge
within the session context." This ADR is the answer.

## Decision

Adopt ADRs as the durable home for architectural decisions in this
codebase. Each ADR captures one decision, the context that forced
it, the trade-offs accepted, and the alternatives we rejected. ADRs
live in `docs/adr/NNNN-kebab-title.md` using a lightweight MADR-ish
format.

Accepted ADRs are NEVER edited \u2014 if a decision changes, we write a
new ADR that supersedes the old one and link both directions.

## Consequences

**Good**:

- Future-us (and future contributors) can answer "why is this
  written this way?" by reading a single 100-line doc rather than
  archaeology-spelunking through commit history.
- Reviewers can flag "this change contradicts ADR-NNNN" instead of
  silently re-introducing a regressed pattern.
- Spec-level decisions (the `specs/NNN-*/spec.md` files) stay
  scoped to ONE feature; cross-cutting decisions (validation
  policy, output parsing, caching) get their own home.

**Trade-offs**:

- Discipline tax \u2014 every architectural decision now needs an ADR.
  We accept this; the alternative cost (re-debugging the same
  problem) is higher.
- Indexing burden \u2014 the README index must stay current. We accept
  this; PR reviewers should flag missing index entries.

## Alternatives considered

- **Keep using long commit messages**. Rejected: commit messages
  aren't browseable by intent, only by time. We can't ask "what
  did we decide about validation?" of a git log.
- **Use inline code comments**. Rejected: comments compete with
  code for screen real estate and developers strip them during
  cleanup passes. ADRs are out-of-band on purpose.
- **Use the `specs/` directory for everything**. Rejected: specs
  describe ONE feature at a time. Cross-cutting decisions (e.g.
  "verifier output parsing tolerance") span multiple specs and
  need their own surface.
- **Use a wiki**. Rejected: wikis drift out of sync with code.
  ADRs live next to the code in git so they're versioned with it.
