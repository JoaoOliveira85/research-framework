# Contract: `SpecConfig` extension

**Owner**: `src/research_vault/spec/schema.py`, validated by `src/research_vault/spec/validator.py`, round-tripped by `src/research_vault/spec/parser.py`.
**Backwards compatibility**: additive only. Existing specs continue to parse without modification (R-007). No field is removed, renamed, or has its type narrowed.

## New fields

### `SpecConfig.forbidden_filename_prefixes`

```python
forbidden_filename_prefixes: list[str] = field(default_factory=list)
```

| Property | Value |
|---|---|
| YAML location | top-level of `research.spec.md` frontmatter |
| Default | `[]` |
| Type | `list[str]` |
| Validation (`validator.py`) | each entry MUST be a non-empty string ending with `_` or `-`; empty list valid |
| Read by | `pipeline/gates_step.py:SG003`, `pipeline/gates_cycle.py:CG003`, abstraction success criterion SC-009 |
| Backwards compat | absent / empty → SG-003, CG-003, SC-009 report `status: "NA"`; never WARN, never FAIL |

**YAML example** (reference_vault_v3 declares the eight known service prefixes):

```yaml
forbidden_filename_prefixes:
  - oms_
  - wms_
  - pim_
  - erp_
  - oebh_
  - oecdh_
  - oehk_
  - cms_
```

**YAML example** (vault that doesn't need the gate):

```yaml
# Field omitted entirely. Abstraction gate reports N/A.
```

### `CoverageCategory.priority`

```python
priority: int = 0
```

| Property | Value |
|---|---|
| YAML location | each entry in the spec's `note_types` array (or wherever `CoverageCategory` is serialized) |
| Default | `0` |
| Type | `int` |
| Validation (`validator.py`) | `0 ≤ priority ≤ 100`; integer; out-of-range → `SpecValidationError` |
| Read by | `pipeline/research_plan.py` for priority-queue ranking; `pipeline/coverage.py:fill_first` for budget-constrained ordering (FR-005) |
| Backwards compat | missing → 0; existing specs see no behaviour change because all categories share priority 0 (preserves spec-author-defined order) |

**YAML example**:

```yaml
note_types:
  - name: spring-feature
    folder: spring/
    priority: 90              # high — fill first
    target_count: 36
  - name: business-flow
    folder: flows/
    priority: 20              # low — only after high-priority categories saturate
    target_count: 50
```

## Validator rules added to `validator.py`

```python
def _validate_forbidden_filename_prefixes(prefixes: list[str], errors: list[str]) -> None:
    for i, p in enumerate(prefixes):
        if not isinstance(p, str) or not p:
            errors.append(f"forbidden_filename_prefixes[{i}]: must be non-empty string")
        elif not (p.endswith("_") or p.endswith("-")):
            errors.append(f"forbidden_filename_prefixes[{i}]={p!r}: must end with '_' or '-'")

def _validate_priority(category_name: str, priority: int, errors: list[str]) -> None:
    if not isinstance(priority, int):
        errors.append(f"note_types[{category_name}].priority: must be int, got {type(priority).__name__}")
    elif not (0 <= priority <= 100):
        errors.append(f"note_types[{category_name}].priority={priority}: must be in [0, 100]")
```

## Round-trip rules (`parser.py`)

- Empty `forbidden_filename_prefixes` MUST be omitted from serialized output to keep specs readable for vaults that don't use the gate.
- `priority == 0` MUST be omitted from serialized `CoverageCategory` output (default value omission).
- Both fields MUST round-trip losslessly when present (parse → serialize → parse produces the same in-memory state).

## Migration path for reference_vault_v3

1. Update `reference_vault_v3/research.spec.md`: add the `forbidden_filename_prefixes` block (8 prefixes shown above).
2. Optionally add `priority` values to high-priority categories (`spring-feature`, `concept`, `java-jvm`, `learning-module`) per spec User Story 3 — recommended values: 90/80/85/75 respectively.
3. Re-run `validate_spec.py --strict`; expect zero new warnings.
4. Next `research-vault generate` (or `research-vault resume`) cycle picks up the new fields automatically.

No data migration required for vault content — only the spec file changes.
