# Quickstart — Acronym-wikilink disambiguation (067)

Reproduce the rc7 corruption, then prove each FR fixes it. All steps are
deterministic (no LLM).

## 0. Reproduce the rc7 failure (baseline)

The live evidence (read-only):

```bash
sed -n '35p' "$HOME/Documents/reference-vault-rc7/data_vault/01 - Concepts/CAP Theorem.md"
# → "The [[cache-aside pattern]] Theorem, formally proven by Eric Brewer…"
cat "$HOME/Documents/reference-vault-rc7/data_vault/cap.md"
# → note_type: alias / redirect_to: cache-aside pattern   (WRONG)
```

A test fixture reproduces the **timeline** that caused it:

1. Cycle A: vault has only `cache-aside pattern` (C-A-P). `CAP` maps unambiguously →
   `cap.md` stub written, any `[[CAP]]` rewritten to `[[cache-aside pattern]]`.
2. Cycle B: `CAP Theorem` (also C-A-P) is added. Today the stale stub + stale body
   link survive → corruption.

## 1. FR1 — single-expansion-only

```python
m = build_acronym_map(vault_dir)
assert "CAP" not in m.mapping        # now ambiguous (2 claims)
assert "CAP" in m.ambiguous
# _write_redirect_stub refuses to (re)create cap.md while CAP is ambiguous
```

## 2. FR2 — self-title protection + stale re-eval

```python
resolve_acronym_links(vault_dir)
body = read("data_vault/01 - Concepts/CAP Theorem.md")
assert "[[cache-aside pattern]] Theorem" not in body   # no sibling rewrite
assert "The CAP Theorem" in body                       # own title preserved
```

## 3. FR3 — verifier FAIL backstop

```python
v = deterministic_wikilink_violations(vault_dir, "01 - Concepts/CAP Theorem.md", corrupted_body)
assert v and v[0]["rule_id"] == "IX-wikilink-title-corruption"   # locked id (analyze A1)
# run_verifier_stage marks the note "rejected"
# a clean note (first link to a genuinely different concept) → no violation
```

## 4. FR4/FR5 — the sweep on an existing vault

```bash
./vault wikilinks                 # dry-run: reports cap.md re-point/delete + CAP Theorem body de-link
./vault wikilinks --fix           # applies repairs
./vault wikilinks --fix           # idempotent: zero actions
./vault wikilinks --json | jq '.[] | {path, action, acronym}'
```

Expected after `--fix`: `CAP Theorem.md` body reads "The CAP Theorem…"; `cap.md`
either re-pointed to a single valid expansion or deleted as an orphan; a second run
is a no-op.

## 5. Quality gate

`build.sh --quality` exercises the acronym fixtures; the FR3 deterministic rule runs
in `run_verifier_stage`, so any reintroduced title-corruption hard-fails the cycle.
`scripts/validate_vault.py` (synced map, D3) WARNs on residual ambiguous links.

## Done-when

- [ ] rc7 CAP timeline fixture produces no corruption (FR1/FR2).
- [ ] Title-corruption note is `rejected` by the deterministic verifier rule (FR3).
- [ ] `./vault wikilinks --fix` repairs a corrupted vault and is idempotent (FR4/FR5).
- [ ] `scripts/validate_vault.py` map stays in sync (D3).
- [ ] `ruff check` + `ruff format --check` clean; `pytest -m "not e2e"` green.
