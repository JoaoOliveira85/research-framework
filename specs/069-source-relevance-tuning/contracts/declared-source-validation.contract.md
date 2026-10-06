# Contract — Declared-source backing validation (069 FR1/FR2)

Owns the deterministic "every declared source must be backed or a strategy hint"
rule, reusing `source_bridge/discovery.py::TriggerRegistry`.

## C1 — Backing rule (FR1)

`source_is_backed(source, registry) -> {backed | strategy_hint | unbacked}`:

- `kind == "strategy_hint"` → `strategy_hint` (valid; no module required).
- else (`module_backed` or absent) → resolve the source **locator** (D2, locked U2:
  first non-empty of `repos[].url`, `repos[].local_path`, `local_path` — no new
  `locator`/`url` field in v1); if it matches ≥1 module trigger via
  `TriggerRegistry.match` → `backed`; else → `unbacked` (absent-`kind` infers the same
  per U3 — no "ambiguous" state).
- `unbacked` is an **error** with message:
  `"source '<name>' declared but has no implementation — add a module whose manifest
  triggers match its locator, or annotate kind: strategy_hint"`.

## C2 — Scaffold gates (FR1)

- `spec/validator.py::validate` (the `generate` path): `unbacked` ⇒ hard validation
  error (blocks scaffold).
- `scripts/validate_spec.py` (vault-spec skill pre-scaffold): `unbacked` ⇒ surfaced
  warning so the operator fixes the spec before generate.
- The manifest JSON schema (`specs/020-code-bridge/contracts/manifest.schema.json`)
  gains `domain` in the trigger-type enum (code already supports it).

## C3 — Runtime fail-closed (FR2)

- `pipeline/preconditions.py` check #6 re-runs the backing rule; an `unbacked`
  source FAILs preflight (clear message), never silently emits empty.
- Because fresh `generate` does not call `preconditions.check` today, the backing
  check is also invoked on the generate path (via C2's validator gate).
- `pipeline/preflight.py::check_all` reports per-source backing status alongside
  connectivity.

## Test obligations

| ID | Assertion |
| --- | --- |
| C1-a | A source whose `repos[].url` matches a module `url_pattern` trigger → `backed`. |
| C1-b | A description-only source (no locator) with `kind: strategy_hint` → `strategy_hint` (ok). |
| C1-c | A description-only source with no `kind` → `unbacked` → error with the source name. |
| C2-a | `spec/validator.py::validate` rejects a spec with an unbacked source. |
| C2-b | `scripts/validate_spec.py` warns on the same. |
| C3-a | Preflight fails closed on an unbacked source; passes on `strategy_hint`. |
| C3-b | rc7's 4 sources: "GitHub" backed (repo URL), the other 3 require `strategy_hint`. |
