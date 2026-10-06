# `atlassian` source module

Surfaces **Jira issues** and **Confluence pages** from Atlassian Cloud via the
**Jira REST API v3** (`/rest/api/3`) and the **Confluence REST API**
(`/wiki/rest/api`). One module, two surfaces, one auth — built on the spec-020
subprocess-isolated module contract, governed by the spec-060 Tier-2 port wave.
This un-parks the previously-deferred `notion/confluence` item (spec-060 Session
2026-06-08) by combining Jira + Confluence on their shared Atlassian surface.

## What it does

Per source URL, the extractor infers the family + key and runs a search:

| `sources.yaml` kind / URL | Fetches |
|---|---|
| `jira_projects` — `.../jira/projects/<KEY>` or `.../browse/<KEY>-123` | recently-updated issues in project `<KEY>` (`/rest/api/3/search`, JQL) |
| `jira_projects` — `.../issues/?jql=<encoded>` | the given JQL (advanced) |
| `confluence_spaces` — `.../wiki/spaces/<KEY>` | recently-modified pages in the space (`/wiki/rest/api/content/search`, CQL) |

It emits a spec-020 `SignalPayload` with one `notable[]` entry per issue/page.
`facts` is empty in v0.1.0 (mirrors the Tier-1 modules); domain-driven fact
buckets are demonstrated in `few-shot.md`.

## Authentication — Basic `email:token` (env only)

Both env vars are **MANDATORY** (the manifest declares them; `preflight.py`
fails the cycle **closed** if either is missing):

```bash
export ATLASSIAN_EMAIL="you@example.com"
export ATLASSIAN_API_TOKEN="…"   # id.atlassian.com → Security → API tokens
```

The module sends `Authorization: Basic base64(email:token)`. The token is sent
**only** in the request header and is never written to stdout/stderr — key-leak
sentinel tests assert this.

> **Security**: API tokens are bearer credentials. Keep them in env vars / a
> secret manager, never in `sources.yaml` or git. Rotate if exposed.

## Hermetic testing

- `ATLASSIAN_API_FIXTURE` — JSON file standing in for the API response. Either
  the raw response (Jira `{"issues": [...]}` / Confluence `{"results": [...]}`)
  or a combined `{"jira": {...}, "confluence": {...}}` mapping. When set, the
  extractor never touches the network and credentials are not required.
- `ATLASSIAN_PREFLIGHT_FAKE_ENV` — JSON mapping of env vars for `preflight.py`.
- `ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE` — `{"ok": bool, "error": str}`.

## Dependencies

Zero new runtime dependencies (Principle V) — stdlib `urllib` / `base64` /
`json` only (the `oreilly` auth precedent).
