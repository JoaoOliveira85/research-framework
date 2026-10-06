# Contract: Spec-020 Amendment Decision Gate

**Spec**: 060 — Source-Module Tier 2+ Port Wave · **Status**: authored 2026-06-03.
Procedure when a candidate module **cannot** satisfy spec-020 contracts without a local
workaround. Outcomes: **amend spec 020**, **approve optional-extra** (Tier 3+ only), or
**defer** — never a per-module hack.

---

## 1. Triggers (invoke the gate when ANY is true)

| ID | Trigger |
|----|---------|
| T1 | Required `source_id` derivation cannot be expressed in `manifest.yaml::source_id_from` |
| T2 | Extractor stdout JSON shape needs fields forbidden by spec-020 facts schema |
| T3 | Hermetic testing is impossible without changing the subprocess contract |
| T4 | Module requires a **new runtime dependency** (Tier 2 always hits this → defer or amend) |
| T5 | Module requires breaking `preflight()` or manifest schema rules from spec 051/020 |

**Non-triggers** (do NOT use this gate): resilience gaps covered by spec 038; vault-local
`scripts/` collectors (legacy — use 020 module path); cosmetic README gaps.

---

## 2. Decision tree

```
Module port blocked on 020 contract?
│
├─ Can fix within 020 five-file template without schema change?
│   └─ YES → implement fix; no gate record needed
│
├─ Needs spec-020 contract change?
│   └─ YES → Path A: Spec-020 amendment (below)
│
├─ Needs new runtime dep (Tier 3+ only)?
│   └─ YES → Path B: Optional-extra (below) OR Path C: Defer
│
└─ Cannot justify amendment or extra?
    └─ Path C: Defer (ladder status → deferred / not_prioritized)
```

---

## 3. Path A — Spec-020 amendment

| Step | Action | Owner |
|------|--------|-------|
| A1 | Open **spec 020** amendment (clarify/plan/tasks in `specs/020-code-bridge/`) | Maintainer |
| A2 | Document breaking change + migration for existing Tier-1 modules | Amendment PR |
| A3 | Ship amendment **before** the module port that depends on it | Release order |
| A4 | Record on ladder: module `status: next` with note `blocked on 020-amendment #PR` | 060 ladder |

**Fail-closed**: port PR MUST NOT merge with a local workaround "until 020 is amended."

---

## 4. Path B — Optional-extra (Tier 3+ only; Principle V exception)

Prerequisites: Tier 2 modules **cannot** use Path B (defer instead).

| Step | Action | Owner |
|------|--------|-------|
| B1 | Write rationale: why stdlib-only is infeasible | Port author |
| B2 | Propose extra name: `research-framework[modules-<name>]` | Port author |
| B3 | Add optional dependency group to `pyproject.toml` (not core deps) | Port PR |
| B4 | Guard imports — framework runs without extra; module fails closed with install hint | Port PR |
| B5 | Maintainer explicit approval in PR review (checkbox) | Maintainer |
| B6 | Acceptance bar §6.2 tests pass | CI |

**Fail-closed**: extra in `[project].dependencies` (unconditional) → reject PR.

---

## 5. Path C — Defer

| Step | Action |
|------|--------|
| C1 | Set ladder `status: not_prioritized` or `parked` with `defer_reason:` |
| C2 | Do **not** merge partial module skeleton that violates 020 |
| C3 | Re-enter ranking when trigger T1–T5 is resolved |

---

## 6. Forbidden outcomes (FR-003, SC-003)

| Forbidden | Example |
|-----------|---------|
| Per-module schema fork | Custom JSON envelope only `hackernews` uses |
| Vault-local extractor bypass | `<vault>/scripts/collect_hn.py` called instead of module subprocess |
| Silent contract violation | Missing `preflight` with module still enabled |
| Unconditional dep | `pypdf` in core dependencies for one module |

---

## 7. Records

| Artifact | Field |
|----------|-------|
| `tier-ladder.contract.md` | `status`, optional `gate: {path, pr, date, reason}` |
| Port PR | Link to 020 amendment PR or defer issue |
| CHANGELOG | User-visible only when amendment or extra ships |

---

## 8. Verdict

| Outcome | Ladder update | Port work |
|---------|---------------|-----------|
| **AMEND-020** | `next` + blocker note | Wait for 020 PR |
| **OPTIONAL-EXTRA** | `next` | Proceed with Path B checks |
| **DEFER** | `not_prioritized` / `parked` | Stop port PR |
