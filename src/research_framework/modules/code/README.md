# `code` source module

Surfaces **local Git working copies** — repositories checked out on disk. Built
on the spec-020 subprocess-isolated module contract (stdin/stdout JSON).

## What it does

Per source (a local `path` under `github_repos` in `sources.yaml`), the
extractor runs `git rev-parse HEAD` to capture the working-copy version and
emits a `SignalPayload`. It is **host/forge-agnostic** — it works for any local
checkout (GitHub, GitLab, self-hosted, or a bare local repo) because it only
reads the filesystem.

## `code` vs `github` — deliberate boundary

These two modules look adjacent but own **disjoint** surfaces (spec-020
amendment, Session 2026-06-08):

- **`code`** (this module) = *local working copies.* Triggers on filesystem
  **paths** (`.git/HEAD`). Does **not** fetch anything remote.
- **`github`** = *remote GitHub surfaces* (PRs / issues / releases via the `gh`
  CLI). Triggers on **`github.com/...` URLs**.

> **History:** `code`'s manifest previously carried a
> `url_pattern: (github|gitlab)\.com/` trigger. That was misleading — the
> extractor has no remote-fetch path, so a bare `github.com/...` URL matched
> `code` and then could not actually be extracted. The `url_pattern` was
> **removed** in v0.1.1; remote GitHub URLs now route to the `github` module.

## Dependencies

Zero runtime dependencies (Principle V) — stdlib `subprocess` plus the host
`git` CLI.
