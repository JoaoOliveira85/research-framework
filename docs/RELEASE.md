# Release process

How to cut a release, what the workflows actually do, and how downstream
vaults take it. This is the only copy of the procedure — `CONTRIBUTING.md`
§ 8 and `CLAUDE.md` § When to bump point here rather than restating it.

## The regime: tags and by hand only

The three workflows under `.github/workflows/` — `ci.yml`, `quality.yml`,
`release.yml` — run **only on a `v*` tag push or a `workflow_dispatch`**. A
push to `main` and a pull request build nothing. That is a rule, not an
accident (`CLAUDE.md` § CI budget): never add a `pull_request`, `push` or
`schedule` trigger, and never a macOS runner without the explicit
`macos: true` dispatch input.

Consequences a maintainer has to hold in mind:

- **The local suite is the merge gate.** A PR reports its own real counts —
  `pytest -m "not e2e"`, `pytest -m e2e`, `python scripts/guards/run_all.py`,
  `ruff check .`, `ruff format --check .` — and "CI shows nothing on this
  PR" is expected.
- **"Merged" is not "released".** The version bump lands on `main` through
  a PR; the *tag* is what cuts the release.
- **The workflows must be enabled on GitHub for a tag to do anything.** If a
  tag fires `release.yml` but not the other two, dispatch them on the tag by
  hand so the release has a CI and quality record:

  ```bash
  gh workflow run ci.yml --ref vX.Y.Z
  gh workflow run quality.yml --ref vX.Y.Z
  gh run list --workflow ci.yml --limit 3      # confirm it actually ran
  ```

  If a run cannot start, the local gates run on the tagged commit are the
  record, and the Release notes should say so.

## Cutting a release (maintainer)

```bash
# 0. Gates, locally, on the commit you are about to release
pytest -m "not e2e" && pytest -m e2e \
  && python scripts/guards/run_all.py \
  && ruff check . && ruff format --check . \
  && bash build.sh --quality

# 1. Bump the version in pyproject.toml   (manual edit; e.g. 1.0.0 -> 1.1.0)

# 2. CHANGELOG.md
#    - promote the [Unreleased] block to [<new-version>] - <TAG DATE>
#    - add a fresh empty [Unreleased] heading for the next cycle
#    - add "### Migration notes" if an existing vault has to do anything

# 3. Refresh the one committed test count
#    docs/testing-strategy.md's <!-- test-count: ... --> marker + its bolded
#    numbers (tests/docs/test_one_source_per_fact.py fails on drift)

# 4. Commit on a release branch, open the PR, merge to main
git checkout -b release/1.1.0
git commit -am "release: 1.1.0 — <one-line summary>"
git push -u origin release/1.1.0 && gh pr create --fill --base main
gh pr merge --merge --delete-branch

# 5. Tag the merge commit on main and push the tag — THIS is the release
git checkout main && git pull --ff-only
git tag -a v1.1.0 -m "v1.1.0" && git push origin v1.1.0

# 6. Verify all three workflows ran on the tag
gh run list --workflow ci.yml --limit 3
gh run list --workflow quality.yml --limit 3
gh run list --workflow release.yml --limit 3
```

### What `release.yml` does

On a `v*` tag push (or a `workflow_dispatch`):

1. **Decides the version.** A tag push uses the tag. A `workflow_dispatch`
   from a branch reads `pyproject.toml`, and if no tag for that version
   exists yet it *creates and pushes it* with `GITHUB_TOKEN` — this is the
   only remaining "auto-detect" path and it is manual (the dispatch), not
   automatic. If the tag already exists it exits cleanly (idempotent).
2. **Verifies the tag matches `pyproject.toml`** and refuses otherwise —
   so tag the merge commit that carries the bump, not the one before it.
3. Builds wheel + sdist (`python -m build`) **and** the install bundle via
   `bash build.sh --quality`, which enforces the mandatory smoke gate
   (ADR-0007) and the spec-022 quality harness across the three committed
   fixtures (`tech-lite`, `source-poor`, `source-rich`) — a >15% regression
   against a committed baseline fails the release.
4. Generates release notes: the git log since the previous tag, the bundle
   and wheel install commands, then GitHub's `generate_release_notes`
   summary appended.
5. Creates the GitHub Release at
   `https://github.com/JoaoOliveira85/research-framework/releases/tag/v<version>`
   with the bundle tarball, wheel and sdist attached.

**Prerelease rule**: a tag is marked prerelease if it contains a hyphen
(`v1.1.0-rc1`) **or** its version contains `rc`, `a`, `b` or `dev`
(`v1.0.0rc1`, `v1.0.0a2`, `v1.0.0b1`, `v1.0.0.dev3` — the PEP 440 forms
hatchling normalises to). A final `vX.Y.Z` carries none of these.

`ci.yml` runs the guard battery, the fast loop, ruff, shellcheck and the
installer dry-run on Linux (macOS only with `macos: true`), plus the
`e2e` job (`pytest -m "e2e and not live_llm"`). `quality.yml` runs
`build.sh --quality` on its own, with an optional single-fixture input.

### Hotfix from a non-main branch

Tag the commit and push the tag; the tag-push path above handles it the
same way (no auto-tag step, since the tag exists).

```bash
git tag -a v1.1.1 -m "v1.1.1" && git push origin v1.1.1
```

## CHANGELOG conventions

- **The heading date is the tag date** (owner decision 2026-09-08, D14):
  `## [X.Y.Z] - YYYY-MM-DD` carries the day `vX.Y.Z` was pushed, not the
  day the block was written. When they disagree, the tag wins.
- Every `### Fixed` bullet in a released block carries `(test: …)`,
  `(regression test: …)` or `(no test: <why>)` on its body
  (`tests/spec/test_changelog_regression_links.py`, in the guard battery).
- **`### Migration notes`** — a sub-block under the version whenever an
  existing vault has to *do* something to take the release: a settings key
  to add, a verb whose exit code changed, a file that is no longer written.
- Headings are unique per block: one `### Added`, one `### Changed`, one
  `### Fixed`, one `### Removed`.

## Versioning policy

- **Package version** (`pyproject.toml`) — semver. PATCH for fixes only;
  MINOR for new verbs, config keys or changed run behaviour; MAJOR for
  removals.
- **Constitution version** (`.specify/memory/constitution.md`) — semver on
  principle changes: PATCH for clarifications, MINOR for new principles,
  new sections and any enforcement downgrade, MAJOR for removals or
  redefinitions (`CONTRIBUTING.md` § 7). Bumps independently of the
  package version.
- **Framework version** (`dist-templates/scaffold-manifest.json`) — bumps
  only on infrastructure-layer scaffold changes. Decoupled from the
  package version — a PATCH package release may bump zero scaffold
  versions; a MINOR release may bump several.

## Pre-release checklist

- [ ] `pytest -m "not e2e"` and `pytest -m e2e` pass locally (the count
      lives in `docs/testing-strategy.md`'s TL;DR marker — this checklist
      quotes none because it always drifts)
- [ ] `python scripts/guards/run_all.py` — every guard PASS
- [ ] `ruff check .` and `ruff format --check .` both clean (separate gates)
- [ ] `bash build.sh --quality` passes locally (smoke gate + spec-022 harness
      across all 3 fixtures; `release.yml` runs the same gate, so local-pass
      means the release will not fail on quality)
- [ ] `docs/testing-strategy.md` test-count marker refreshed
- [ ] `pyproject.toml` version reflects the release you're cutting
- [ ] `CHANGELOG.md`: `[Unreleased]` promoted to `[<version>] - <tag date>`,
      fresh empty `[Unreleased]` added, every `### Fixed` bullet annotated,
      `### Migration notes` present if any vault has to act
- [ ] `docs/ROADMAP.md`: tier rows flipped to `[x]` for what shipped; a
      shipped-registry row for the version
- [ ] `README.md` "current stable" pointer and `CLAUDE.md`'s header version
      + "Recent Changes" (pruned to the last 5 ship cycles)
- [ ] Every spec shipped under this release has `**Status**:
      shipped(<date>, <PR/commit>)` (`tests/docs/test_spec_status_headers.py`
      enforces the vocabulary; `tests/docs/test_shipped_tasks_are_a_ledger.py`
      the ledger)
- [ ] If any principle changed: constitution bumped with a Sync Impact Report
- [ ] **After the tag**: all three workflows ran (`gh run list`); epic
      trackers / issues closed with `Closes #N`; every live vault updated
      (`./vault update`) and, if the release changed spending or run
      behaviour, `cycle --estimate-only` run once per vault (exit 2 = do
      not schedule)

## Installing a release (user)

Two paths — pick based on whether you want a vault scaffolded or just the
Python package.

### Full vault install (recommended for end users)

```bash
# Current stable is v1.0.0 (2026-10-06); check the Releases page for newer
curl -L https://github.com/JoaoOliveira85/research-framework/releases/download/v1.0.0/research-framework-1.0.0.tar.gz \
  | tar -xzf - -C /tmp
cd /tmp/research-framework-1.0.0
./install.sh ~/vaults/my-vault
```

`install.sh` is idempotent — it (re-)scaffolds the vault according to
`dist-templates/scaffold-manifest.json` while respecting the
`is_user_owned_after_first_write` flag on user-owned files (won't
overwrite your edits). The bundle carries all six settings profiles
(`settings.yaml`, `.codex`, `.cursor`, `.cursor-claude`, `.opencode`,
`.ollama` — see `dist-templates/README.md` § Switching runtimes); a local
/ self-hosted model path is always supported.

### Python package only

```bash
pip install \
  https://github.com/JoaoOliveira85/research-framework/releases/download/v1.0.0/research_framework-1.0.0-py3-none-any.whl
```

Or directly from the repo (always-latest):

```bash
pip install git+https://github.com/JoaoOliveira85/research-framework@main
```

There is no PyPI publication — spec 041 (release infrastructure v2) is a
v2.0.0 candidate on `docs/ROADMAP.md`, and its premise (per-PR CI,
auto-detect on a `pyproject` bump) has to be re-scoped to the tag-time
regime before it is planned.

## Updating an existing vault to the new release

```bash
cd ~/vaults/<vault>
./vault update
```

`./vault update` (spec 027):

1. Refuses to run on a dirty working tree (pre-flight guard) — commit
   first.
2. `pip install --upgrade` of the framework into the vault's venv
   (`RV_GITHUB_REPO` / `RV_GITHUB_REF` override the source; default is the
   published repo at `main`).
3. Downloads the matching release archive and re-executes the bundled
   `install.sh` against the vault, which re-scaffolds framework-owned files
   — including `<vault>/scripts/` — and leaves user-owned ones alone.

What it still does not do: pin or diff versions (no "before → after"
report), short-circuit when nothing changed, run offline, or rewrite a
**user-owned** file such as `settings.yaml` — which is why the next
section exists.

## Migration notes (operator)

Because `settings.yaml` is user-owned after first write, a release that
changes what a settings key *means* does not reach vaults that already
have the file. When a release does, its CHANGELOG block carries a
`### Migration notes` sub-block with the per-vault step.
