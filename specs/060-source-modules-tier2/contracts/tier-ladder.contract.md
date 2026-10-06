# Contract: Source-Module Tier Ladder (authoritative)

**Spec**: 060 — Source-Module Tier 2+ Port Wave · **Status**: authored 2026-06-03.
**Authoritative** module-coverage list (FR-005, SC-005). `docs/ROADMAP.md` § Source Modules
roadmap mirrors this artifact at doc-sync time — on conflict, **this file wins**.

---

## 1. Status enum

| Status | Meaning |
|--------|---------|
| `shipped` | Stock module in framework release; Tier-1 = 0.6.0 baseline |
| `next` | Next prioritized for port work under 060 bar |
| `in_progress` | Port PR open |
| `future` | On ladder; Tier 4 — not actively ported |
| `parked` | Explicitly deferred (low demand or blocked ecosystem) |
| `not_prioritized` | On ladder; no active port planned (Tier 3 default) |
| `subsumed` | Covered by another module (no separate port) |
| `deferred` | Amendment gate Path C — see `gate` field |

Optional `gate` object: `{ "path": "AMEND-020"|"OPTIONAL-EXTRA"|"DEFER", "reason": "...", "pr": "..." }`

---

## 2. Tier 1 — shipped (0.6.0)

| Module | Status | Notes |
|--------|--------|-------|
| youtube | shipped | Wave 2 |
| reddit | shipped | Wave 2 |
| rss | shipped | Wave 2; subsumes arxiv |
| oreilly | shipped | Wave 2; auth-gated |
| arxiv | subsumed | Use `rss` module |
| code | shipped | Pre-Wave-2 stock |

---

## 3. Tier 2 — active scope (ranked)

Priority rank from `research.md` D2. **Batch-1 kickoff**: rank 1 only.

| Rank | Module | Status | Priority rationale |
|------|--------|--------|-------------------|
| 1 | hackernews | **next** | Highest demand + rss/reddit pattern fit + stdlib + low effort |
| 2 | wikipedia | not_prioritized | Starts after rank-1 bar validated |
| 3 | newsletters | not_prioritized | Format fragmentation; after top-2 |
| 4 | blog_posts | not_prioritized | Scraping variance |
| 5 | conference_talks | not_prioritized | youtube overlap; lower marginal value |
| 6 | github_extras | not_prioritized | Auth + API cost; oreilly pattern when started |

---

## 4. Tier 3 — ladder only (defer-by-default)

| Module | Status | Notes |
|--------|--------|-------|
| pdfs | not_prioritized | Likely needs optional-extra; defer per research D3 |
| podcasts | not_prioritized | Feed stdlib possible; transcribe path TBD |
| epub | not_prioritized | Parser extra likely; defer |
| twitter | parked | Auth + API volatility |
| mastodon/bluesky | not_prioritized | API surface TBD |

---

## 5. Tier 4 — future (out of active scope)

| Module | Status | Notes |
|--------|--------|-------|
| social_bookmarklet | future | User-initiated CSV import; not batch-1 |

---

## 6. Parked — out of active scope

| Module | Status | Notes |
|--------|--------|-------|
| slack/discord exports | parked | Ecosystem export dependency |
| email | parked | IMAP/auth complexity |
| notion/confluence | parked | MCP overlap; separate strategy |
| goodreads | parked | Low demand signal |

---

## 7. Maintenance rules

| Event | Action |
|-------|--------|
| Port ships | `status` → `shipped`; bump rank-2 to `next` if bar validated |
| Port PR opened | `status` → `in_progress` |
| Amendment gate defer | `status` → `deferred` + `gate` object |
| Demand signal shifts | Re-run rubric in `research.md`; update rationale column only |
| Subsume discovered | `status` → `subsumed` + pointer module |

---

## 8. Doc-sync mirror (not authoritative)

After ladder edits, implementer updates `docs/ROADMAP.md` § Source Modules roadmap table
to match §2–§6 — same module names, same ordering, `(governed by spec 060)` annotation
preserved.
