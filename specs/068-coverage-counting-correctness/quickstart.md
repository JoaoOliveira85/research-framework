# Quickstart — Coverage counting correctness (068)

Reproduce the `0% → 0%` lie, then prove the disk recompute fixes it. Deterministic
(no LLM).

## 0. Reproduce the rc7 failure (baseline)

```bash
cd "$HOME/Documents/reference-vault-rc7"
# ~107 notes on disk:
for d in data_vault/[0-9]*; do echo "$(ls "$d"/*.md 2>/dev/null | wc -l)  $d"; done
# but the stored count is tiny:
python3 -c "import json; d=json.load(open('_pipeline/coverage-targets.json')); print({c['name']: c['met_count'] for c in d['categories']})"
# → {'concepts': 2, 'algorithms': 2, ...}  (sums to ~14, not ~107)
sed -n '20p' "data_vault/01 - Concepts/ACID.md"   # coverage_category: concepts  (matches the slug!)
```

The digest then reports `0% → 0% (+0%)` and "stagnant" for every category.

## 1. FR1 — recompute from disk

```python
from research_framework.pipeline.coverage import recompute_from_disk
t = recompute_from_disk(vault_dir)
by = {c.name: c.met_count for c in t.categories}
assert by["concepts"] == 20      # was 2
assert sum(by.values()) >= 100   # was ~14
```

## 2. FR2 — cycle-end invariant

```python
# after a cycle writes N notes:
recount = recompute_from_disk(vault_dir)
assert sum(c.met_count for c in recount.categories) == notes_written_this_run + prior
# divergence is surfaced loudly, never silent
```

## 3. FR3/FR4 — digest + status agree, no more 0% → 0%

```bash
./vault digest   # Coverage Delta shows real %, Gaps no longer all "stagnant"
./vault status   # same coverage numbers as the digest (one source of truth)
```

> **Scope note (analyze I2):** derive-on-read fixes the **current** coverage % and all
> **forward** cycle-to-cycle deltas immediately. It does NOT rewrite already-committed
> historical per-cycle reports — those stale `0%` snapshots stay as written history
> (Vault-History-Append-Only). The first post-fix digest simply shows the corrected
> current baseline; deltas from that point on are accurate.

## 4. FR5 — quality fixture guards the regression

```bash
bash build.sh --quality   # multi-category fixture asserts non-zero coverage %; fails if 0% → 0% returns
```

## Done-when

- [ ] `recompute_from_disk` counts all on-disk notes by frontmatter `coverage_category` (FR1).
- [ ] Cycle-end invariant holds; divergence surfaces (FR2).
- [ ] Digest shows real coverage %, not `0% → 0%`; `./vault status` matches (FR3/FR4).
- [ ] `build.sh --quality` multi-category fixture is green and would catch a regression (FR5).
- [ ] Stale vaults (incl. rc7) self-heal on next read — no migration verb (Q3).
- [ ] `ruff check` + `ruff format --check` clean; `pytest -m "not e2e"` green.
