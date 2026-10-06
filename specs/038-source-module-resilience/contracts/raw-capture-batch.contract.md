# Contract: `scripts/raw_capture_batch.py` (spec 038 FR-006/007, US3)

**Status:** PROPOSED (ships with spec 038)
**Builds on:** `scripts/raw_capture.py` (0.6.2) — reuses `capture()` as the
per-URL primitive. **Does NOT fork** the capture logic.
**Decided (Q1):** a single centralized batch script run OUTSIDE the agent loop
(sandbox-proof), NOT a per-module hook.

---

## 1. Why a batch driver

The 2026-05-13 feeds-vault incident: a sandboxed LLM agent writes notes but cannot
fetch `source_urls` from inside its sandbox. `raw_capture_batch.py` runs after the
cycle on the HOST (which has network), reads the new notes' `source_urls`, and
mirrors each URL locally so Tier-2 citation durability (Principle IX) survives both
the sandbox block AND later link-rot.

## 2. CLI

```bash
scripts/raw_capture_batch.py --vault <path> [--cycle N] [--since <ISO8601>] [--dry-run]
```

- `--vault` (required): vault root.
- `--cycle N` / `--since`: scope to notes produced this cycle (default: notes
  changed since the last batch run, tracked by the manifest's newest timestamp).
- `--dry-run`: enumerate URLs + planned actions, write nothing.

## 3. Input — new-note `source_urls`

Read frontmatter via the canonical `vault/frontmatter.py` parser (FR-011 reuse).
Collect every `source_urls` entry from in-scope notes; de-dup by `sha256(url)`.
Each unique URL records its **citing notes** (list of note paths).

## 4. Output layout

```text
<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json   # the index (NEW)
<vault>/raw_data/<year>/<month>/<slug>-<hash>.<ext>    # bytes (existing capture() layout)
```

The batch is the **index**; byte-mirroring is delegated to the shipped
`raw_capture.capture(url, raw_data_dir, source_type)` which keeps its `year/month`
layout. (Plan flags an alternative: a `capture(target_dir=…)` override to land
bytes literally under `captures/<DATE>/<sha256>.<ext>` per the literal FR-006 path
— resolved at /tasks.)

### `manifest.json` schema

```jsonc
{
  "schema_version": "1.0",
  "cycle": 7,                          // null when --since drove the scope
  "generated_at": "2026-06-03T20:00:00Z",
  "captures": {
    "<sha256-of-url>": {
      "url": "https://example.com/post",
      "status": "OK | FAILED | PENDING",
      "captured_path": "raw_data/2026/06/post-ab12cd34.html",  // null when FAILED/PENDING
      "captured_at": "2026-06-03T20:00:01Z",                   // null until OK
      "error": "network error: timeout",                       // present only on FAILED
      "payload_kind": "rich | thin | js_shell | binary",       // from capture() meta
      "citing_notes": ["data_vault/Topics/Foo.md", "..."]
    }
  }
}
```

## 5. Behaviour

| Situation | Action |
| --- | --- |
| URL not yet captured | Call `capture()`; on success record `OK` + path + `payload_kind`; on network failure record `FAILED` + `error`. |
| URL already `OK` in manifest | Skip (idempotent — FR-007). `capture()` itself is also idempotent on existing `meta.json`. |
| URL `FAILED`/`PENDING` in a prior run | Re-attempt (partial-run resume — FR-007). |
| Any per-URL failure (5xx/timeout) | Record `FAILED`, CONTINUE. **Batch exits 0** even if all URLs fail (US3 non-fatal; SC-002). |
| Interrupted (Ctrl-C/OOM) | Manifest written incrementally; resume re-fetches only non-`OK` entries (edge case from spec). |
| Same URL in 50 notes | Captured ONCE (`sha256(url)`); `citing_notes` lists all 50. |
| `--dry-run` | Print plan; write nothing; exit 0. |

## 6. Exit codes

- `0` — batch completed (even with FAILED URLs, or zero URLs).
- `2` — bad args / vault not found / unreadable frontmatter (abort).

(There is deliberately no non-zero "some URLs failed" code — US3 is non-fatal.)

## 7. Principle V / test discipline

- Network access is via the shipped `capture()` only; tests stub `capture()` (no
  real network) and assert dedup, manifest shape, idempotent resume, and exit-0.
- No new runtime dependency.
- Never writes outside `<vault>/raw_data/`.
