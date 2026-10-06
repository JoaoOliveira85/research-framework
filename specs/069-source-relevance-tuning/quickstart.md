# Quickstart — Source-relevance + declared-source validation (069)

Reproduce the rc7 silent-empty, then prove validation + the stagnant signal fix it.
Deterministic (no LLM); FR4 relevance tuning is a separate sub-spec.

## 0. Reproduce the rc7 failure (baseline)

```bash
cd "$HOME/Documents/reference-vault-rc7"
ls -d modules 2>/dev/null || echo "NO modules/ dir"          # → NO modules/ dir
grep -A1 "name:" research.spec.md | grep -E "name|access_method"
# 4 declared sources, all free-text access_method, none module-backed → 3 went cold silently
```

## 1. FR1 — backing validation at scaffold

```python
from research_framework.spec.validator import validate
# rc7-shaped spec: "GitHub" has repo URLs matching the github module trigger → backed;
# "Web"/"Official Documentation"/"Codebase Vault Seed" have no module → error unless strategy_hint
errs = validate(spec_without_kind)
assert any("declared but has no implementation" in e for e in errs)

# annotate the three as strategy_hint → passes:
errs2 = validate(spec_with_strategy_hints)
assert not errs2
```

## 2. FR2 — runtime fail-closed

```bash
./vault   # generate/resume: an unbacked declared source FAILs preflight with a clear message
# (never silently emits empty signals as rc7 did)
```

## 3. FR3/FR5 — stagnant-source WARN

```bash
./vault status   # a source cold ≥2 cycles shows a WARN; an authoritative cold source ranks first
# advisory only — the cycle is not blocked
```

## 4. Drop-in module path (the operator's model)

```bash
# Adding a source = dropping a module whose manifest declares matching triggers:
cat <vault>/modules/<name>/manifest.yaml   # triggers: [{type: url_pattern, pattern: ...}]
# the declared source's locator (repo URL / path) now matches → backed, no strategy_hint needed
```

## Done-when

- [ ] An unbacked declared source errors at scaffold with its name (FR1).
- [ ] `kind: strategy_hint` sources pass; trigger-matched sources pass (FR1).
- [ ] Preflight fails closed on an unbacked source (FR2).
- [ ] A source cold ≥2 cycles → advisory WARN in cycle report + `./vault status`,
      authority-weighted (FR3/FR5); never blocks the cycle.
- [ ] Operator-driven migration: framework warns, never rewrites `research.spec.md` (Q2).
- [ ] FR4 relevance-classifier tuning filed as a follow-up sub-spec (Q3).
- [ ] `ruff check` + `ruff format --check` clean; `pytest -m "not e2e"` green.
