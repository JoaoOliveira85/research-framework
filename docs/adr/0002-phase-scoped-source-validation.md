# ADR-0002: Phase-scoped `sources_consulted` validation

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: validation, spec-019, 0.2.30, scout, research

## Context

The spec H2 enforcement (introduced in 0.2.28) requires every
`required: true` data source in the vault spec to appear in the
report's `sources_consulted` list. The intent was to make sure the
spec is the law: if a source is marked required, the cycle must
actually touch it.

In 0.2.29 we discovered this enforcement was uniform across
pipeline stages, and that was wrong. The vault spec routinely has
two kinds of required sources:

- `role: intent` (e.g. GitHub PRs, Confluence pages) \u2014 these
  describe what the engineering org INTENDS to build. The scout
  stage needs them.
- `role: domain` (e.g. AWS DynamoDB docs, the Kafka manual) \u2014
  these are external reference material. The scout does NOT need
  them; the research stage does.

Uniform enforcement meant: the scout was required to "consult"
domain sources it had no business reading. The scout had two bad
choices: list the domain sources in `sources_consulted` (lie about
having read them), or fail validation. Both happened. In the
user's reference-vault-0.2.29 trial, the scout failed validation on
domain sources EVEN THOUGH the corresponding research stage would
have consulted them correctly two steps later.

This is a textbook case of one validator being applied to a context
it wasn't designed for \u2014 the same shape "required source must be
consulted" means different things at different points in the
pipeline.

## Decision

Make `sources_consulted` validation phase-aware. The validator now
filters the set of `required` sources by phase:

- **scout phase** \u2192 require only sources with `role` in
  `{behaviour, intent}`. `role: domain` sources are filtered out.
- **research phase** \u2192 require all `required` sources (existing
  behaviour).

Other phases default to "require all required sources" unless they
declare a `_ROLES` constant in `validate_cycle.py`. Adding a new
phase with phase-specific roles is a one-line addition.

Implementation: `scripts/validate_cycle.py::_spec_data_sources()`
accepts an optional `phase` argument; `check_termination_v2` passes
the report's `phase` field. The filter is `if phase == "scout":
roles = _SCOUT_PHASE_ROLES`.

## Consequences

**Good**:

- The scout no longer has to lie about consulting domain sources.
- Validation errors point at the RIGHT problem ("scout didn't
  consult an intent source") instead of the wrong one ("scout
  didn't consult a domain source it has no reason to read").
- The pattern is extensible: every new phase can declare its own
  source-role expectations.

**Trade-offs**:

- The validator now has a per-phase branch. We accept the
  complexity \u2014 the alternative (uniform enforcement) is wrong.
- We need to keep phase-role mappings in sync with the spec
  template. Drift surfaces as a clear "phase X is treating roles
  Y, Z as required" log line; it doesn't silently corrupt anything.

## Alternatives considered

- **Mark every domain source as `required: false`**. Rejected:
  domain sources are GENUINELY required for the research stage to
  produce good notes. Downgrading them would weaken research-stage
  enforcement.
- **Split into two source lists per phase in the spec**. Rejected:
  duplicates configuration; users would have to maintain two
  parallel lists.
- **Add a `consumed_by: [scout, research]` field on each source**.
  Rejected: pushed complexity onto the user. The role-based filter
  already encodes the same information implicitly.

## Tests

`tests/scripts/test_validate_cycle_phase_scoped_sources.py` covers
the six phase\u00d7role combinations including the user's specific
0.2.29 failure shape.
