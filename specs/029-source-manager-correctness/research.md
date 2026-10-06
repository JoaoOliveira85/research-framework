# Research & Decisions: 029 Source Manager Correctness

Phase 0 decisions. Inputs: the clarify Session 2026-06-03 + a code audit at the 053 base
(`pipeline/source_manager.py` — `record_cycle`, `_count_notes_referencing`, `mark_degraded`;
`pipeline/_cycle_helpers.py` — `notify_required_source_degraded`; plus `coverage.py`,
`steps/research.py` for the `notes_created` shape).

## The audit (both bugs re-verified present, 12 days after the draft)

| Bug | Spec claim (2026-05-22) | Code reality at 053 base | Verdict |
|---|---|---|---|
| **1** | `notify_required_source_degraded` calls `mark_degraded` with 2 args, always hits except, `source-incidents.md` never written | `md(source_name, reason)` at the call site; `mark_degraded(name, reason, vault_dir)` needs 3. **Now wrapped in `try/except` that logs a warning** (not silent), AND a parallel `cycle-NNN-source-incidents.json` sidecar **is** written. | **CONFIRMED** (markdown still never written); symptom evolved |
| **2** | `record_cycle` counts `notes_generated` by substring-matching URL vs file paths | Verbatim: `if url in str(note_path) ... elif name.lower() in note_str.lower()` | **CONFIRMED verbatim** |

Unlike spec 039 (whose premise was stale), 029's premise **holds** — the fixes are real. The
audit's value was surfacing the *evolutions* (the JSON sidecar; the warning-not-silent; the
existing `_count_notes_referencing` frontmatter scanner) that reshape the FRs.

## D1 — Bug 1 fix: 3-arg call + **narrow** the except (don't just widen the catch)
**Decision**: change the call to `md(source_name, reason, vault_dir)` (vault_dir is the
function's first param). Narrow the surrounding `except Exception` to `except OSError` so a
genuine markdown-write failure is still tolerated, but a `TypeError` (signature mismatch) **propagates** — turning a silent class of bug into a loud one.
**Why**: the broad catch is *why* the bug shipped silently (it swallowed the `TypeError`).
Leaving it broad would let a future re-break re-hide. SC-004 (revert-the-fix → test fails)
only works if the error surfaces.
**Rejected**: keeping `except Exception` (re-hides future arity breaks); removing the try
entirely (a real disk-full/permission error writing the operator log shouldn't abort a cycle).

## D2 — Bug 2 fix: one shared predicate `_note_cites_source(fm, name, url)`
**Decision**: extract the matching logic into `_note_cites_source(frontmatter, source_name,
source_url) -> bool` and route **both** `record_cycle`'s `notes_generated` (per-cycle, over
`notes_created`) and `_count_notes_referencing` (all-time, over `data_vault/`) through it.
**Why**: the two metrics must never disagree on *what counts as a citation*. Today
`notes_referencing` already scans frontmatter correctly while `notes_generated` scans paths —
the divergence is the bug. One predicate = one source of truth (DRY + correctness).
**Rejected**: fixing `notes_generated` with its own inline frontmatter scan (duplicates the
parse; invites future drift from `_count_notes_referencing`).

## D3 — Resolving `notes_created` to readable files: mirror `coverage.py`
**Decision**: `notes_created` entries may be **bare filenames** (`"Foo.md"`) **or vault-relative
paths** (`"data_vault/01 - Concepts/Foo.md"`) — confirmed by the comment + code in
`coverage.py::assign_categories` (lines 276-280) and `steps/research.py` (line 353-354). FR-002
resolves each via `Path(name).name` + `rglob` under `data_vault/` — the **exact pattern
`coverage.py` already uses** to read created-note frontmatter for category assignment.
**Why**: `coverage.py` is the established precedent for "open each note this cycle created and
read its frontmatter." Reusing the resolution strategy guarantees FR-002 sees the same files
the coverage gate does (consistency). Basename+rglob handles both path shapes; the bare
`(vault_dir / rel)` join in `steps/research.py` does not handle bare filenames.
**Rejected**: assuming `notes_created` are always resolvable relative paths (false — bare
filenames occur); requiring callers to pass `notes_dir` (optional today; can't rely on it).

## D4 — `normalize_source_url()`: strip fragment + trailing slash, **keep query**
**Decision**: a stdlib `urllib.parse`-based helper that lowercases scheme + host, strips a
trailing `/` from the path, and drops `#fragment` — but **preserves the query string**.
Matching (per Q3) is `normalize(entry) contains/equals normalize(source.url)` **OR**
`source_name in entry` (name fallback).
**Why**: trailing-slash and fragment differences are noise; but query strings are **load-bearing**
for the project's own source conventions — O'Reilly uses `learning.oreilly.com/search/?q=…`,
YouTube uses `watch?v=…`, RSS feeds disambiguate by `?feed=`. Dropping the query would collapse
distinct sources. The name fallback (Q3) preserves the current reach so notes that cite a source
by name (not exact URL) keep counting.
**Rejected**: stripping query (breaks oreilly/youtube/rss source identity); full URL canonicalization
incl. sorting query params (over-engineered for substring matching; risks false merges).

## D5 — `source-incidents.md` recovery: append-only with a `Resolved` line (Q2)
**Decision**: keep `mark_degraded`'s append-only write; add a sibling `mark_resolved(name,
vault_dir)` (or a `state="resolved"` arg) that appends `- <ts> — \`<name>\` resolved`.
`notify_required_source_degraded` calls it when a previously-degraded required source has
citations again. Current state = "last line per source wins" (readers + the JSON sidecar give
the structured view).
**Why**: audit trail beats mutate-in-place; aligns with the framework's append-only ethos
(Principle X spirit) and avoids a read-modify-rewrite race on the markdown.
**Rejected**: self-pruning the file (loses history; needs a parse-rewrite that can corrupt a
hand-edited operator log).

## D6 — Reconciliation: undo wrongful archival, not a per-cycle rebuild (Q4)
**Decision**: `scripts/reconcile_source_metrics.py` targets the bug's *durable* harm —
sources wrongly auto-archived. Per source it computes `cited_now` (notes in the **current**
`data_vault/` that cite it, via the D2 predicate), then **un-archives** any `status='archived'
AND cited_now>0` source and **resets `consecutive_empty_cycles=0`** where `cited_now>0`;
uncited sources are untouched. `--dry-run` prints a per-source action table, zero mutations;
`--apply` writes only `sources.db`. Idempotent; never touches notes.
**Why schema-honest**: `notes_generated` is a **per-cycle** column on `source_cycles`; cumulative
`total_notes_generated` is a derived `SUM`, not a stored field — so "recompute the cumulative
column" is a category error. Per-cycle history can't be faithfully rebuilt either (notes get
edited/deleted between cycles). But the decision that *matters* — "is this source archival-eligible
*now*?" — is driven by `sources.consecutive_empty_cycles` + `status`, both directly correctable
from `cited_now`. Zero-false-positive on a clean vault (SC-005) falls out because a never-buggy
vault already has `cited_now`-consistent state.
**Rejected**: git-history per-cycle rebuild (fragile, slow, needs the full commit DAG — and 050
only guarantees commits *exist*, not diff-stable note bodies); "recompute cumulative
notes_generated" (no such stored column); dropping FR-008 (leaves wrongly-archived sources dead
until manual un-archive).

## Cross-spec: 049 (Wave 1 cycle-helpers split)
`notify_required_source_degraded` is in `_cycle_helpers.py`, which 049 splits into
`pipeline/_helpers/`. 049 is Wave 1, lands before 029 (Wave 2). The FR-001 fix is one line
wherever it ends up; FR-005's test imports from the **post-049** path. Action: rebase 029 onto
`main` after 049 merges. No logic conflict — purely an import location.
