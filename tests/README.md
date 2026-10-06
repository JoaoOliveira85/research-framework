# tests/

Source of truth for what we test, how we test it, and which tier each test
belongs to. Read `docs/testing-strategy.md` for the full seven-tier pyramid
(restructured under ADR-0008, 2026-05-21).

## Directory map

Tier numbers per ADR-0008. Old tier 4 (single-cycle e2e) became tier 5
(Cycle e2e); a new tier 4 (Component integration) absorbs sub-cycle
tests like `test_cycle_runner.py` and `test_orchestrator.py`.

| Path | Purpose | Tier |
|------|---------|------|
| `tests/_helpers/` | Reusable infrastructure — `fake_agent.py`, `vault_factory.py`, their contract tests. | 2 |
| `tests/pipeline/` | Pipeline modules — slicer, gates, research plan, cycle runner, **component integration (tier 4)**, **cycle e2e (tier 5)**, **multi-cycle (tier 6)**. | 1 / 3 / 4 / 5 / 6 |
| `tests/scripts/` | Bundled scripts under `scripts/` — validators, vault audit, source preflight. | 1 / 2 |
| `tests/cli/` | CLI surface — `research-framework` commands, onboard, prune, migrate. | 1 / 3 |
| `tests/agents/` | Skill / agent invocation tests. | 1 / 2 |
| `tests/generator/` | Vault scaffold + render + scripts copy. | 1 / 2 |
| `tests/processors/` | Source preprocessing / archive / extract / verify. | 1 |
| `tests/collectors/` | RSS / source collectors. | 1 |
| `tests/scaffold/` | Scaffold-manifest / template-version emission. | 1 / 2 |
| `tests/spec/` | Spec schema + validation (and cross-cutting lint guards). | 1 / 2 |
| `tests/contracts/` | Committed JSON Schemas wired to real producer output (#295, #326). | 2 |
| `tests/docs/` | Doc-truth guards — one-source-per-fact, spec index, prompt corpus, status headers. | 2 |
| `tests/vault/` | Note format, frontmatter, credibility, wikilinks, claims export. | 1 / 2 |
| `tests/quality/` | Spec-022 harness — metric calculators, baselines, the regression gate. | 2 / 6 |
| `tests/benchmark/` | Spec-056 executor × model harness (kept OUT of every gate). | 1 / 2 |
| `tests/observability/` | Spec-048 log surfaces and the source-consideration ledger. | 3 |
| `tests/source_bridge/` | Spec-020 bridge — discovery, consensus, watermarks, validators. | 1 / 3 |
| `tests/modules/` | The shipped source modules' extractors and preflights. | 1 / 3 |
| `tests/foreman/` | ADR-0010 Arm A verifier — the `tasks.md` parser and its checks. | 1 / 2 |
| `tests/integration/`, `tests/e2e/` | Cycle e2e and budget/pause paths (tiers 5-6). | 5 / 6 |
| `tests/build/` | **Hard build-gate enforcement (tier 7).** | 7 |
| `tests/fixtures/` | Shared fixtures and golden artefacts. | n/a |

## Markers

Two axes per ADR-0008: **scope** (where in the pyramid) and **purpose**
(why the test exists). Markers compose freely.

| Marker | Axis | What it means | Default sweep includes it? |
|--------|------|---------------|----------------------------|
| (none) | scope | Default unit / contract / integration / component — fast. | yes |
| `@pytest.mark.e2e` | scope | Tier 5 (single-cycle) or tier 6 (multi-cycle) — drives real cycle runner. | yes |
| `@pytest.mark.slow` | scope | Subprocess-heavy (e.g. invokes `build.sh`). | yes (but consider `-m "not slow"`) |
| `@pytest.mark.live_llm` | scope | Real LLM CLI call — **costs money**, must be opted in explicitly. Renamed from `integration` in ADR-0008. | **no — skipped by default by `tests/conftest.py`; opt in via `--live-llm` or `LIVE_LLM=1`** |
| `@pytest.mark.regression` *(voluntary)* | purpose | Test exists to prevent a specific shipped `CHANGELOG.md` bug from recurring. | yes |
| `@pytest.mark.acceptance` *(voluntary)* | purpose | Test proves a specific `specs/NNN-*/spec.md` acceptance scenario. | yes |

## Which automation runs what

A marker is a promise that something runs the test. Until issue #266 the
`e2e` marker was not: 17 of the 27 `e2e`-marked tests ran in no automation
at all, and `docs/testing-strategy.md` said markers "govern the local
developer loop only". They do not — CI selects by marker in two jobs.

**Every workflow runs on a `v*` tag push or a manual
dispatch only** — never per PR, push or schedule (`CLAUDE.md` § CI budget).
The merge gate is the **local** suite: `pytest`,
`python scripts/guards/run_all.py` and `ruff`, which every PR reports.

| Automation | Trigger | What it actually runs |
|------------|---------|-----------------------|
| the local gate | every PR, by hand | `pytest`, `scripts/guards/run_all.py`, `ruff check`, `ruff format --check` |
| `.github/workflows/ci.yml` job `ci` (Linux; macOS only on a `macos: true` dispatch) | `v*` tag, manual dispatch | `pytest -m "not e2e"`, `ruff check`, `ruff format --check`, `check_portability.py`, `shellcheck`, installer dry-run |
| `.github/workflows/ci.yml` job `e2e` (Linux) | same | `pytest -m "e2e and not live_llm"` (~6.5 min) |
| `build.sh` § 0 smoke gate | Local; also inside `build.sh --quality` | `pytest "${SMOKE_TESTS[@]}"` — **file paths, no `-m`**, so markers do not apply |
| `.github/workflows/quality.yml` | `v*` tag, manual dispatch | `build.sh --quality`: the smoke gate, then `research_framework.quality.runner` — **not pytest** for the harness itself |
| nothing | — | `live_llm` — opt in locally with `--live-llm` / `LIVE_LLM=1`; real money |

`tests/build/test_e2e_tier_runs_in_automation.py` enforces this: an
`e2e`-marked file must be in `SMOKE_TESTS` or covered by the `e2e` job, and
`tests/pipeline/test_runner_agent_dispatch.py` must stay **unmarked** (only
`-m "not e2e"` reaches it, and it is the spec-209 regression gate).

## Common invocations

```bash
pytest -m "not e2e and not slow"   # fast local loop (tiers 1-4 + cheap tier-2/7)
pytest                              # full sweep including e2e
pytest tests/_helpers/              # fake-agent + vault-factory contracts
pytest tests/pipeline/test_cycle_runner.py    # tier-4 component integration
pytest tests/pipeline/test_full_cycle_e2e.py -v    # tier-5 cycle e2e
pytest -m slow                      # include the build-gate proof
pytest -m regression                # run the historical bug-catalogue tests
pytest -m "acceptance and not e2e"  # fast slice of spec-acceptance proofs
pytest --live-llm                   # OPT-IN: also run live_llm tests (real claude/codex; real money)
LIVE_LLM=1 pytest                   # same — env-var alternative for CI matrices
./build.sh                          # runs the smoke gate then builds the wheel
```

## Adding a test

1. Read `docs/testing-strategy.md` § "Which tier do I add a test at?".
2. Pick the **lowest** tier that catches your change.
3. If you need to stub out an LLM call, use `tests/_helpers/fake_agent.py` —
   never a hand-rolled `subprocess` mock.
4. If you need a temp vault, call `vault_factory.build_minimal_vault(tmp_path)`.
   If you need a stand-in cycle runner, pass the `cycle_runner=` seam with a
   stub from `tests/_helpers/cycle_runner_stub.py` — monkeypatching
   `run_cycle_steps` is refused by a guard (#86).
5. Mark e2e tests with `pytestmark = pytest.mark.e2e` so they can be skipped
   in the fast loop.
