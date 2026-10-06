# `github` source module

Surfaces **remote GitHub activity** — pull requests, issues, and releases — for
repositories you enumerate in `sources.yaml`. Built on the spec-020
subprocess-isolated module contract (stdin/stdout JSON), governed by the
spec-060 Tier-2 port wave.

## What it does

Per source URL (`github.com/<org>/<repo>[/<surface>]`), the extractor fetches
recent items via the **`gh` CLI** (`gh api repos/<org>/<repo>/...`) and emits a
`SignalPayload` with one `notable[]` entry per item. The *surface* is inferred
from the URL path:

| URL shape | Surface fetched |
|---|---|
| `.../<org>/<repo>` | releases (default) |
| `.../<org>/<repo>/pulls` (or `/pull/<n>`) | pull requests |
| `.../<org>/<repo>/issues` (or `/issues/<n>`) | issues |
| `.../<org>/<repo>/releases` | releases |

`facts` is intentionally empty in v0.1.0 (mirrors the Tier-1 modules); the
domain-driven fact buckets are demonstrated in `few-shot.md`.

## Authentication — `gh` session, NOT an API key

This module uses the host **`gh` CLI session**. There is no API key in
`sources.yaml` or in any env var. Authenticate once:

```bash
gh auth login        # interactive, persists a session token (~24h+)
gh auth status       # confirm you are logged in
```

The module's `preflight.py` runs `gh auth status` and **fails the cycle closed**
(`fatal_fail`) if you are not authenticated — extraction depends on the session.

## `code` vs `github` — deliberate boundary

These two modules look adjacent but own **disjoint** surfaces (spec-020
amendment, Session 2026-06-08):

- **`code`** = *local working copies.* Triggers on filesystem **paths**
  (`.git/HEAD`); its extractor only runs `git rev-parse HEAD` and local file
  walks. It is host/forge-agnostic (works for any local checkout). It does
  **not** fetch anything remote.
- **`github`** = *remote GitHub surfaces.* Triggers on **`github.com/...` URLs**;
  its extractor shells `gh api`. It does **not** read local files.

A local checkout and its remote are distinct sources that can both be
enumerated without colliding in the first-match trigger registry.

## Hermetic testing

- `GH_BIN` — override the `gh` binary path (point at a fake script).
- `GH_FIXTURE` — a JSON file standing in for the `gh api` response (a bare list
  of items, or a `{surface: [items]}` mapping). When set, the extractor never
  shells `gh`.
- `GITHUB_PREFLIGHT_AUTH_FIXTURE` — `{"ok": bool, "error": str}` standing in for
  `gh auth status` in `preflight.py`.

## Dependencies

Zero new runtime dependencies (Principle V) — stdlib `subprocess`/`urllib`/`json`
plus the host `gh` CLI (a host tool, not a Python package).
