# Contract — benchmark opencode support + optional label (spec 056)

## FR-018/019 — opencode is a benchmark cell (free)

- `benchmark/matrix.py::valid_runtimes()` already unions `_RUNTIME_ADAPTERS ∪
  _HTTP_RUNTIMES` from `agent_call.py`. Once opencode is registered, it is allowed.
- **Guard test (MUST)**: `assert "opencode" in valid_runtimes()`. This is the only
  required benchmark change for FR-018/019.
- An `executors: [{runtime: opencode, models: [m1, m2]}]` block MUST expand to one
  `Cell(task, "opencode", m_i)` per model × task (existing `cells()` product).

## FR-020 — optional `label` (SHOULD, low-effort)

Matrix YAML:

```yaml
executors:
  - runtime: opencode
    label: opencode-local-qwen      # OPTIONAL
    models: [ollama/qwen2.5:7b]
  - runtime: opencode
    label: opencode-gpt5            # OPTIONAL
    models: [openai/gpt-5.4]
```

- `_parse_executors` MUST accept an optional `label: str`; absent ⇒ `None`.
- `Executor` gains `label: str | None = None`.
- Cell display token:
  - `label is None` ⇒ `f"{task}__{executor}__{model}"` (BYTE-IDENTICAL to today).
  - `label` set ⇒ `f"{task}__{label}__{model}"`.
- `reporter.py` uses the same display token in its rows.

## MUST NOT

- Make `label` required (breaks every existing matrix YAML + the byte-identical default).
- Touch runner/scoring/gating semantics — display + keying only.

## Tests

- guard: `"opencode" in valid_runtimes()`.
- expansion: an opencode block with 2 models × N tasks → 2N cells.
- label set → key/report uses the label; two opencode blocks with distinct labels
  → two distinct cells for the same runtime.
- label absent → key byte-identical to pre-064 (SC-008).
