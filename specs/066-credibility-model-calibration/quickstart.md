# Quickstart: Credibility-model calibration (spec 066)

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-15

Reproduce the rc7 failure, then prove each FR fixes it. Uses the real
`~/Documents/reference-vault-rc7/` evidence as the worked example.

---

## 0. The bug (reproduce against rc7)

```bash
cd ~/Documents/reference-vault-rc7
# 12 notes were rejected with the same credibility verdict:
rg -l 'verifier_status: rejected' _pipeline/quarantine/ | wc -l        # → 12
rg 'no source default applies' _pipeline/quarantine/Fastify.md          # → 3 hits
# the offending citations are plain-string canonical-domain URLs:
sed -n '/source_urls/,/summary/p' _pipeline/quarantine/Fastify.md
#   - https://fastify.dev/
#   - https://fastify.dev/docs/latest/Reference/Routes/
#   - https://github.com/fastify/fastify
```

Root cause: no inline `credibility`, no `data_sources[].default_credibility`,
and (pre-066) no domain catalog ⇒ `CredibilityUnresolved` ⇒
`IX-credibility-unresolved` FAIL ⇒ reject.

## 1. FR1 — default catalog grades canonical domains

```bash
python - <<'PY'
from pathlib import Path
from research_framework.vault.credibility import load_catalog   # new (FR1)
cat = load_catalog(Path("~/Documents/reference-vault-rc7").expanduser())
for url in [
    "https://fastify.dev/",
    "https://github.com/fastify/fastify",
    "https://en.wikipedia.org/wiki/CAP_theorem",
    "https://docs.aws.amazon.com/lambda/",
    "https://spark.apache.org/docs/",      # *.apache.org wildcard → tier_3
    "https://github.com/",                 # bare host → miss (needs ≥2 path segs)
]:
    print(f"{url:55} -> {cat.lookup(url)}")
PY
# fastify.dev      -> Level.CORROBORATED   (tier_2)
# github.com/...   -> Level.CORROBORATED   (tier_2, host_path ≥2 segs)
# en.wikipedia.org -> Level.PRIMARY        (tier_1)
# docs.aws...      -> Level.PRIMARY        (tier_1)
# spark.apache.org -> Level.COMMENTARY     (tier_3 wildcard)
# github.com/      -> None                 (ungraded — needs a repo path)
```

## 2. FR2 — unknown well-formed URL is WARN, not FAIL

```bash
# Re-run the verifier credibility check on a quarantined note:
python - <<'PY'
from pathlib import Path
from research_framework.pipeline.verifier import deterministic_credibility_violations
v = Path("~/Documents/reference-vault-rc7").expanduser()
note = v / "_pipeline/quarantine/Fastify.md"
viol = deterministic_credibility_violations(v, note.name, note.read_text())
print(viol)   # post-066: [] (all three hosts are catalog tier_2/tier_1) ⇒ no rejection
PY
```

A genuinely-unknown well-formed host (e.g. `https://kubernetes.default.svc/`)
yields one `IX-credibility-unresolved` with `severity: warn` — surfaced as an
advisory `verifier_note`, **not** a rejection. A malformed host
(`http://prometheus:9090/`, host has no dot) still FAILs on the existing
`IX-citation-malformed` rule.

## 3. FR3 — vault-local override (settings.yaml)

```yaml
# ~/Documents/reference-vault-rc7/settings.yaml  (add this section)
credibility:
  unknown_domain_policy: warn          # default; set 'reject' for strict vaults
  trusted_domains:
    - domain: "internal.companyhost.com"
      tier: tier_1
    - domain: "wikipedia.org"          # Q11: silently DOWN-grade a default
      tier: tier_3
      notes: "This vault treats Wikipedia as commentary only"
```

```bash
# wikipedia.org now resolves tier_3 (commentary) for THIS vault, no warning:
python - <<'PY'
from pathlib import Path
from research_framework.vault.credibility import load_catalog
cat = load_catalog(Path("~/Documents/reference-vault-rc7").expanduser())
print(cat.lookup("https://en.wikipedia.org/wiki/X"))   # -> Level.COMMENTARY (override won)
PY
```

Strict mode: set `unknown_domain_policy: reject` to restore the rc7-pre-066 FAIL
on unknown hosts (catalog-hit hosts still grade by tier).

## 4. FR4 — `./vault re-grade` reinstates the quarantined notes

```bash
cd ~/Documents/reference-vault-rc7

# Dry-run first (touches nothing, no commit):
./vault re-grade --dry-run
#   reinstated: 9   still-quarantined: 2   skipped (non-credibility): 1
#   Fastify.md → data_vault/06 - Frameworks/Fastify.md (tier_2 via fastify.dev)
#   ...

# Real run — moves + restamps + one commit:
./vault re-grade
#   Committed regrade(2026-06-15): 9 notes reinstated  (abc1234)

git log --oneline -1               # → regrade(2026-06-15): 9 notes reinstated
ls _pipeline/quarantine/           # → only the genuinely-failing notes remain
rg -l 'verifier_status: verified' "data_vault/06 - Frameworks/Fastify.md"   # reinstated
```

Idempotent: a second `./vault re-grade` finds nothing to do — no-op, no commit.
A single note: `./vault re-grade --note "_pipeline/quarantine/Fastify.md"`.

## 5. FR5 — regression guard

```bash
cd ~/src/research-framework
bash build.sh --quality          # the tech-stack fixture (rc7-class hosts) must
                                 # keep verifier-rejection rate ≤ 10% — a regression
                                 # re-introducing the rc7 symptom fails here, not at
                                 # live-validation time.
```

## Acceptance coverage (filled at /speckit.tasks)

| Requirement | Evidence (test) |
| --- | --- |
| FR1 catalog + tier map | `tests/vault/test_credibility_catalog.py` |
| FR2 ungraded WARN / malformed FAIL / catalog-hit unchanged | `tests/vault/test_credibility.py`, `tests/pipeline/test_verifier.py` |
| FR3 override section + full-replace + strict mode | `tests/pipeline/test_settings_credibility.py` |
| FR4 re-grade reinstate/skip/dry-run/commit/destination | `tests/cli/test_regrade.py`, `tests/cli/test_vault_script_new_verbs.py` |
| FR5 regression fixture ≤10% | `tests/fixtures/quality/<tech-stack>` + baseline |
