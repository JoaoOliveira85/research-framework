# ADR-0013: Cross-repo envelopes are additive within a major, carry `schema_version`, and get their schema before their producer

**Status**: Accepted (2026-09-08)
**Date**: 2026-09-08
**Tags**: cross-repo, contracts, schema-evolution, spec-036, principle-xi
**Evidence base**: constitution v1.5.0 Principle XI and § Cross-Repo
Obligations (two rows **Not met**, one **Non-compliant** and already
breached by F9); spec 036 Q1 open since 2026-05-27; issue #189 (a consumer
in `consumer_pipeline` parsing this repo's note frontmatter by hand); owner
decision D5 of 2026-09-08.

## Context

Principle XI says every payload this repo exchanges with a sibling is a
contract, and that a contract must have a written form, a version carried
in the payload, a named counterparty, a mirror in the counterparty with a
guard, and a row in the obligations register. The register then grades the
repo against its own rule and finds it satisfies none of the five rows
fully. The two `assistant-framework` rows are **Not met** because the
schemas spec 036 names (`tests/contracts/vault-ask-1.0.schema.json`,
`tests/contracts/research-result-1.0.schema.json`) were never written, and
the `consumer_pipeline` row is **Non-compliant** because the note format has no
version field at all — which is how F9 rewrote that payload across seven
live vaults without the consumer being able to notice.

Spec 036 has carried three clarifications since May. Q1 is the one this ADR
answers, because it is not a per-feature decision: *how does a payload
another repo reads evolve?* Whatever 036's `ask` envelope decides, the inbox
envelope (036 US2), the claims export #189 asks for, and — when it finally
gets one — the note format will face the same question. Answering it three
times, differently, is the "shape that survives only in one author's head"
Principle XI was written against. CONTRIBUTING § 6 says a decision that
crosses spec boundaries is an ADR, and the owner's instruction was explicit:
the ADR comes before any schema is written.

The two forces in tension are a consumer's need to refuse a shape it does
not understand, and a producer's need to add a field without breaking every
consumer it has never met. Full semantic versioning with breaking minors
serves the first and punishes the second; no version field at all serves
neither, as F9 showed.

## Decision

1. **Every cross-repo payload carries `schema_version` in the payload
   itself**, as a string `"<major>.<minor>"`. It is the first thing a
   consumer reads. This applies to the spec-036 `ask` envelope and inbox
   envelope, to the #189 claims export when it is specified, and to any
   future payload a sibling reads. It is the version rule for the note
   format too, once `079` T003's vocabulary question is settled and a
   version key can be named; until then that row stays honestly
   **Non-compliant**.

2. **Within a major, evolution is append-only.** A minor bump may add
   optional fields and add enum members whose absence a `x.0` consumer
   already tolerates. It may never remove, rename or retype a field, change
   the meaning of an existing enum member, or make an optional field
   required. Consumers ignore fields they do not know. A `1.0` consumer
   therefore accepts every `1.x` payload; the schema says so mechanically
   with `additionalProperties: true` and a `schema_version` pattern of
   `^1\.[0-9]+$`.

3. **A major bump is a new schema file**, `<name>-<major>.0.schema.json`,
   beside the old one, which is kept for at least one release so a consumer
   can validate what it is still receiving. A consumer MUST refuse a major
   it does not know; it MUST NOT guess.

4. **The schema is written and wired to a test before the producer
   exists.** `tests/contracts/vault-ask-1.0.schema.json` ships with this ADR,
   pinned by `tests/contracts/test_vault_ask_envelope_schema.py` against
   hand-written contract fixtures — explicitly *not* producer output,
   because there is no producer yet. When 036 T001 builds one, the fixture
   test stays and a second test validates real output, the way #326 did for
   the state file. A schema that exists only in prose is the "written form"
   Principle XI already rules out.

5. **`schema_version` is a safeguard, recorded but not acted on.** No
   negotiation, handshake or migration code is built now. The field exists
   so that a consumer *can* refuse, and so that a future migration has a
   number to key on. Building version machinery for a payload with zero
   consumers would be Principle VIII's placeholder in another form.

6. **The mirror and its guard are the consumer's obligation to accept and
   this repo's to name.** The mirror is a byte-for-byte copy of the schema
   file in the consumer repo, and the guard is a test in each repo that
   compares its copy against the other's committed copy — the shape
   `consumer_pipeline` already uses for the website's design tokens. Neither
   exists until a consumer does; the obligations register keeps saying so.

## Consequences

**Good**
- Spec 036's Q1 is answered once, for every payload, and its status can
  move from "awaiting clarify" to `planned` with an FR that names a real
  file.
- #189 inherits a policy instead of re-deciding one: the claims export,
  whatever verb carries it, is a `schema_version`-bearing additive
  envelope. Whether it is `./vault export --claims` or a 036 payload is
  #189's own decision and is not made here.
- The obligations register's two **Not met** rows gain a written form.
  They do not become **Enforced** — there is no producer, no mirror and no
  guard — and this ADR does not pretend otherwise. The constitution's own
  rows are amended in the 1.6.0 pass, not here.
- A consumer built against `1.0` keeps working through `1.7`; the day a
  field must change meaning, the number says so.

**Trade-offs**
- Append-only within a major means dead fields accumulate until a major
  bump; the cost is carried by the producer, deliberately, because the
  producer is the party that can see every consumer's version and the
  consumer is not.
- `additionalProperties: true` weakens what a schema can catch on the
  producer side (a typo'd optional field validates). The producer test, when
  it exists, must assert the exact key set it writes; the schema is the
  consumer's floor, not the producer's ceiling.
- A version field with nothing acting on it can look like ceremony. It is
  the cheapest possible insurance against the failure this repo has
  already had (F9), and it costs one line per payload.

## Alternatives considered

- **Full SemVer with breaking minors** (spec 036 Q1's other option).
  Rejected: it makes every minor a negotiation, and with consumers in
  repos this repo does not control, a negotiation is a deploy-ordering
  problem. The additive rule lets producer and consumer deploy in either
  order within a major.
- **No version field; rely on the schema file's name.** Rejected: the
  consumer receives bytes, not a filename. F9 is the demonstration — the
  note payload changed shape and nothing in the payload said so.
- **A shared contracts repository.** Rejected by Principle XI already: a
  third deploy unit and a third place to forget, and it breaks spec 036
  US3's deploy-time separability.
- **Write the producer first and derive the schema from its output.**
  Rejected: that is how `agent-call-record.schema.json` came to describe a
  shape its writer never used (#295). The schema is the contract; the
  producer conforms to it.

## Relationship to other ADRs and specs

- Implements the "written form" and "version carried in the payload" halves
  of constitution Principle XI for the payloads it names; the mirror and
  guard halves are recorded as owed, not met.
- Spec 036 § Clarifications records Q1 as resolved by this ADR; Q2 and Q3
  are per-feature and stay in the spec.
- Spec 080's `run.json`, spec 081's `triage.json` and `078`'s sidecar are
  in-repo payloads, not cross-repo ones, but they adopt the same
  `schema_version` rule so the framework has one evolution story rather
  than two.
- Does not supersede any ADR. ADR-0011 (run-control config lives in
  settings) governs where 036's `integrations.assistant.*` keys go.

## Tests

- `tests/contracts/test_vault_ask_envelope_schema.py` — the schema is a
  valid 2020-12 schema; a minimal `1.0` envelope validates; a `1.3` envelope
  with an unknown optional field validates (the additive rule, pinned);
  a `2.0` envelope is refused; `confidence` outside `[0, 1]`, a missing
  required key, and a citation without `note_path` are each refused; the
  "cannot answer" shape spec 036 FR-006 requires validates.
