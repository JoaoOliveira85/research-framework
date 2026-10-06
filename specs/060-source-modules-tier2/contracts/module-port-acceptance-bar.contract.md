# Contract: Per-Module Port Acceptance Bar

**Spec**: 060 — Source-Module Tier 2+ Port Wave · **Status**: authored 2026-06-03.
Normative pass/fail checklist for **every** Tier 2+ module port. A port ships only when
**all** items pass. Invoked by port PR review; no speckit sub-spec per module.

**Not in this bar** (spec 038 — sequenced separately): EMPTY vs FAILED distinction, client
rate-limit enforcement, raw-URL capture batch, archive.org fallback, extended install probes
beyond spec-051 `preflight()`.

---

## 1. Scope

Applies to modules under `src/research_framework/modules/<name>/` (stock) and their vault
copies at `<vault>/modules/<name>/`. Tier 2 ports MUST satisfy §2–§7. Tier 3+ ports also
satisfy §8 when invoking an optional-extra.

---

## 2. Spec-020 five-file template (FR-002a)

| # | Check | Pass criterion |
|---|-------|----------------|
| 2.1 | `manifest.yaml` present | Valid per spec-020 manifest schema; includes required `preflight` key (spec 051) |
| 2.2 | `extractor.py` present | Subprocess JSON contract; no agent dispatch inside extractor |
| 2.3 | `preflight.py` present | Invokable; exits 0 on healthy fixture env |
| 2.4 | `few-shot.md` present | Non-empty scout examples |
| 2.5 | `README.md` present | Operator setup + env vars documented |
| 2.6 | `sources.yaml.template` present | Enumerates representative source shapes |

**Fail**: any file missing or manifest lacks `preflight` → port blocked.

---

## 3. Hermetic contract tests (FR-002b)

| # | Check | Pass criterion |
|---|-------|----------------|
| 3.1 | Test module exists | `tests/modules/test_<name>_contract.py` (or equivalent tier-2 path) |
| 3.2 | Hermetic | No live network; env overrides (`_*_BIN`, `_*_FIXTURE`) per Tier-1 precedent |
| 3.3 | Coverage | Happy path + empty result + error/auth path + truncation boundary where applicable |
| 3.4 | CI | `pytest -m "not e2e"` green with new tests |

**Fail**: tests hit live APIs or skip error paths → port blocked.

---

## 4. Spec-022 quality harness (FR-002c, FR-007)

| # | Check | Pass criterion |
|---|-------|----------------|
| 4.1 | Harness run | `bash build.sh --quality` executed on PR branch |
| 4.2 | Hold-or-improve | All three fixtures (`tech-lite`, `source-poor`, `source-rich`) ≤ baseline regression tolerance (no new regressions) |
| 4.3 | Evidence | PR body or checklist cites harness result |

**Fail**: any fixture regression → port blocked until fixed or baseline intentionally updated
with separate governance approval (outside port PR).

---

## 5. Mandatory preflight (FR-002d — spec 051)

| # | Check | Pass criterion |
|---|-------|----------------|
| 5.1 | `manifest.yaml::preflight` | Points at module `preflight.py` entry |
| 5.2 | Orchestrator | Module not skipped-with-WARN for missing preflight |
| 5.3 | Tests | Preflight contract test: missing env → non-zero exit + clear stderr |

**Fail**: absent preflight or silent skip → port blocked.

---

## 6. Dependency policy (FR-002e, FR-004)

| Tier | Rule |
|------|------|
| Tier 2 | **Zero** new entries in `[project].dependencies`; stdlib + existing `pyyaml`/`jinja2` only |
| Tier 3+ (no extra) | Same as Tier 2 until 020-amendment gate approves an optional-extra |
| Tier 3+ (with extra) | Extra named `research-framework[modules-<name>]`; documented in port PR; import guarded |

| # | Check | Pass criterion |
|---|-------|----------------|
| 6.1 | `pyproject.toml` | No new unconditional runtime deps |
| 6.2 | Optional import | If extra used: ImportError path tested when extra absent |

**Fail**: unconditional dep added → port blocked.

---

## 7. Auth-gated modules (FR-004 — when applicable)

Modules requiring credentials (e.g. `github_extras`, future `twitter`) MUST additionally:

| # | Check | Pass criterion |
|---|-------|----------------|
| 7.1 | Auth pattern | Follow `oreilly` module: env var documented, probe in preflight |
| 7.2 | Key-leak safety | Contract test asserts sentinel API key absent from payload+stdout+stderr |
| 7.3 | Skip logging | Unconfigured module logs skip reason (Principle VII) |

**N/A** for modules with no secrets (e.g. `hackernews`, `wikipedia`).

---

## 8. Overlap / subsume rule

If a candidate module is a strict subset of an existing module (precedent: `arxiv` ⊂ `rss`):

| # | Check | Pass criterion |
|---|-------|----------------|
| 8.1 | Decision | Subsume into existing module OR defer — no duplicate extractor |

---

## 9. Port PR checklist (operator-facing)

Copy into port PR description:

```markdown
## 060 acceptance bar
- [ ] Five-file template (§2)
- [ ] Hermetic contract tests (§3)
- [ ] build.sh --quality hold-or-improve (§4)
- [ ] Mandatory preflight (§5)
- [ ] Dependency policy (§6)
- [ ] Auth-gated checks if applicable (§7)
- [ ] No 020 workaround (amendment gate if needed)
```

---

## 10. Verdict

| Result | Meaning |
|--------|---------|
| **PASS** | All applicable sections pass → module may ship |
| **FAIL** | Any applicable check fails → port blocked |
| **DEFER** | Routed through `020-amendment-gate.contract.md` → explicit deferral recorded on ladder |
