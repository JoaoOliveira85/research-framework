# Facts-Schema Generation Prompt (v1)

Used by `schema_gen.py` at install time and on `research.spec.md` hash
change. Per D1, this prompt produces a per-`(vault, module)` JSON
Schema for the `facts` bucket of SignalPayload.

**Resolution**: This is a `tier: basic` call (per D7). Default model
is the basic-tier identifier from `settings.yaml::tiers.basic`.

## Inputs to the prompt

Bound from the framework at runtime:

| Variable | Source | Description |
|----------|--------|-------------|
| `{{spec_md}}` | `<vault>/research.spec.md` | Full spec markdown bytes |
| `{{module_name}}` | `manifest.yaml::name` | e.g. `code`, `youtube`, `reddit` |
| `{{module_description}}` | `manifest.yaml::description` | One-line description |
| `{{schema_examples}}` | Module's `schema_examples` file | Few-shot examples |

## Prompt template

```text
You are generating a JSON Schema (Draft 2020-12) that defines what
STRUCTURED FACTS the `{{module_name}}` data-source module should
extract from sources in this specific research vault.

The vault's research specification is below. Your job is to identify
WHAT DOMAIN-RELEVANT CATEGORIES this vault cares about, then emit a
JSON Schema where each top-level property is one such category.

## Critical principles

1. **Domain-agnostic by construction.** Do NOT default to web /
   programming categories. If the spec describes embedded firmware,
   your schema is about firmware concerns. If it describes ML
   pipelines, your schema is about ML concerns. If it describes
   biology research, your schema is about biology concerns. Take
   your cue from the spec, not from your training data.
2. **Categories are buckets that GROW.** Each top-level property
   should be something multiple extracted signals can fill over time
   (technologies, patterns, decisions, constraints, etc.).
3. **Prefer 3-8 top-level buckets.** Fewer buckets = clearer
   extraction. More buckets = noise.
4. **Use the module's few-shot examples to calibrate granularity.**
   The examples show what KIND of buckets are appropriate for this
   module, NOT which specific buckets to include.

## Module context

Module name: `{{module_name}}`
Module description: `{{module_description}}`

Few-shot examples from this module:

{{schema_examples}}

## Research vault specification

{{spec_md}}

## Output

Emit a single JSON Schema (Draft 2020-12) document. Wrap it in a
```json fenced code block. The schema's top-level `properties` are the
domain-relevant buckets you identified. Include short `description`
strings on each property explaining what kinds of signals belong
there. Mark essential buckets in `required`.
```

## Output validation

The framework validates the response by:

1. Extracting the first ```json fenced block.
2. `json.loads()` on the contents.
3. Checking it's a valid JSON Schema (has `$schema` or at least
   `type: object` + `properties`).
4. On any failure: log WARN, fall back to the 3-bucket default
   (`technologies`, `patterns`, `notable`).

## Idempotency note

Schema-gen is invoked rarely (install + spec-hash change). Model
non-determinism MAY produce slightly different schemas across runs;
the framework treats this as a feature (re-running on spec change
intentionally surfaces new categories). The `bridge_compat` field on
the manifest is for module authors who want to lock to a specific
schema shape; out of scope for v1.

## Test fixtures

Phase 2 ships these test inputs:

- `tests/fixtures/vault-microservices/research.spec.md` \u2014 expect
  schema with web-centric buckets.
- `tests/fixtures/vault-embedded-firmware/research.spec.md` \u2014 expect
  schema with firmware-centric buckets (no `api_protocols`, instead
  `peripherals`, `timing_constraints`, etc.).

The contract test (`test_schema_gen.py::test_domain_divergence`)
runs schema-gen on both fixtures, asserts the resulting schemas have
\u2264 30% bucket-name overlap. Validates SC-005.
