# Implementation Plan: Layered Testing Strategy

**Branch**: `018-testing-strategy` | **Date**: 2026-05-17 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/018-testing-strategy/spec.md`

## Summary

After three consecutive seam-bug releases (0.2.20 → 0.2.21 → 0.2.22), the existing 1053-test suite has been proven inadequate at one specific category of failure: **contract mismatches between two correct sub-components**. This plan adds the missing tier-3 (seam) and tier-4/5 (single-/multi-cycle end-to-end) infrastructure to the existing `pytest` suite, plus a hard gate in `build.sh` that prevents shipping a bundle whose e2e tier is red.

The strategy hinges on a single reusable artefact — `tests/_helpers/fake_agent.py` — that replaces the real `scripts/agent_call.py` during tests. Once this fake exists, tier-4 e2e tests become cheap (< 5s each, $0 token cost) and tier-5 multi-cycle tests become viable (< 15s each). Without the fake, neither tier exists.

The plan touches no production code beyond `build.sh` and a documentation page. The cycle runner, batch slicer, research plan, and gate framework are all unchanged by this feature — they are the **subjects** of the new tests, not the targets of modification. Any test that fails on first run reveals a bug that gets a separate fix in a separate PR.

## Technical Context

**Language/Version**: Python 3.11+ (matches the rest of the codebase per constitution Technology Constraints).

**Primary Dependencies**: existing — `pytest ≥ 7` (already in `[project.optional-dependencies.dev]`), `pyyaml ≥ 6.0` (used by `fake_agent.py` to produce valid frontmatter), `jinja2 ≥ 3.1` (not used directly by the fake — the cycle runner renders prompts that the fake then consumes as plain text). **No new runtime or dev dependencies.** Hypothesis is already a dev dep but explicitly out of scope for this feature (spec § Out of Scope).

**Storage**: Test artefacts under `tmp_path` only. No fixtures persist between test runs. The fake agent writes to `tmp_path / "_pipeline" / "cycles"` and `tmp_path / "data_vault"` — the same layout the real cycle runner produces — so no test-only data formats are introduced.

**Testing**: `pytest` (existing config in `pyproject.toml`: `addopts = "-v --tb=short"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`). New tests follow existing layout:
- `tests/_helpers/fake_agent.py` (new) — reusable stub module.
- `tests/_helpers/vault_factory.py` (new) — reusable temp-vault builder.
- `tests/_helpers/__init__.py` (new) — package marker.
- `tests/pipeline/test_full_cycle_e2e.py` (new, US2) — tier-4 single-cycle scenarios.
- `tests/pipeline/test_multi_cycle_e2e.py` (new, US3) — tier-5 multi-cycle scenarios.
- New marker `@pytest.mark.e2e` registered in `pyproject.toml` so developers can run `pytest -m "not e2e"` for the unit-tier-only fast loop and `pytest -m e2e` for the gate suite.

**Target Platform**: macOS / Linux developer workstations and `build.sh` invocations. No CI infrastructure changes (out of scope). The hard gate runs locally during bundle build.

**Project Type**: Single project — test infrastructure addition. No new packages, no new entry points, no new CLI flags on the production code.

**Performance Goals**:
- Tier-4 single-cycle e2e: each scenario < 10 s; the file's full sweep < 30 s.
- Tier-5 multi-cycle e2e: each scenario < 30 s; the file's full sweep < 90 s.
- Combined e2e gate run by `build.sh`: < 60 s wall-clock total (parallel-friendly).
- Full test suite including e2e: < 3 minutes total (spec § Constraints).

**Constraints**:
- **Zero real LLM calls in any test.** Every external agent invocation goes through `tests/_helpers/fake_agent.py`. No exceptions.
- **No new dependencies.** Stdlib + pytest + existing dev deps only.
- **Test determinism.** Same input → byte-identical output. The fake agent uses no randomness; the `vault_factory` produces stable paths and seeds.
- **Backwards compatibility.** Existing 1053 tests must keep passing unchanged. The old stub at `tests/fixtures/stubs/claude` is grandfathered until the new tier-4 tests are proven on `fake_agent.py`; deletion is a follow-up PR.
- **No agent self-assessment in fakes.** The fake agent emits exactly what its inputs imply, no judgment calls. (Mirrors constitution Principle IV.)

**Scale/Scope**:
- ~6 new test files (3 helpers, 2 e2e, 1 spec-compliance check).
- ~600 lines of test code total.
- 1 build.sh modification (~15 lines for the smoke gate).
- 1 new doc (`docs/testing-strategy.md`, ~100 lines).
- 1 CHANGELOG entry per release that adds tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution version: **1.3.1**. Each principle evaluated against the spec + clarifications:

| Principle | Status | Justification |
|---|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | PASS | This feature *adds* a deterministic Python gate (`build.sh` smoke gate, US4) on top of the existing test framework. The gate logic is `pytest` exit code — pure Python. No agent self-assessment introduced. |
| **II. Phase Sequencing (NON-NEGOTIABLE)** | PASS | New tests exercise the existing phase sequence; they do not change it. The fake agent honors the same phase contract (scout → research → validate) as the real one. |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | PASS | This feature *is* the test-first apparatus the rest of the codebase relies on. The implementation order (tasks.md) builds the fake-agent module before the e2e tests, and each e2e scenario is written as RED-first against the existing production code — bugs that fail RED get fixed in separate PRs. |
| **IV. Agent-Script Separation of Concerns** | PASS | The fake agent is a pure script — it does not invoke an LLM, it does not make judgment calls. It is deterministic input → deterministic output. This is the strictest possible interpretation of Principle IV: the test agent never "decides" anything. |
| **V. Offline-First, No External Data Persistence** | PASS | No network calls, no external data sources, no new dependencies. The entire test suite runs offline by construction. |
| **VI. No Duplicate Notes** | PASS | The fake agent produces deterministic filenames keyed off topic titles — duplicates can only arise from a deliberately-constructed test scenario. |
| **VII. External Sources Are Mandatory** | N/A | Tests stub external sources; the constitution principle applies to production behavior, not test fakes. |
| **VIII. No Placeholders / Stub-as-Fuel** | PASS | The fake agent is a test-only stub, explicitly NOT a production placeholder. It lives under `tests/` and is never imported by `src/research_vault/`. |
| **IX. Vault-First Citation (NON-NEGOTIABLE)** | PASS | The fake agent emits valid Tier 1 + Tier 2 citations in every note frontmatter so the existing verifier passes; this is how we test the verifier, not how we bypass it. |
| **Two-Layer Vault Architecture** | PASS | The `vault_factory` produces the canonical two-layer layout (Layer 1 inventory at vault root, Layer 2 content under `data_vault/`); tests exercise the projection contract rather than working around it. |
| **BFS → DFS → Repeat Research Model** | PASS | Tier-4 tests exercise one BFS→DFS pass; tier-5 tests exercise the repeat boundary. The fake agent honors the same stage sequencing as production. |
| **Technology Constraints** | PASS | Python 3.11+, stdlib + pytest + pyyaml. No new dependencies. |

**Verdict**: All non-negotiable principles satisfied. Proceed to Phase 0.

## Project Structure

```text
specs/018-testing-strategy/
├── spec.md            # User scenarios + acceptance criteria (this feature)
├── plan.md            # This document
├── tasks.md           # Ordered task list (next file)
└── contracts/
    └── fake-agent.contract.md   # Input/output contract for fake_agent.py

tests/
├── _helpers/                       # NEW — reusable test infrastructure
│   ├── __init__.py
│   ├── fake_agent.py               # Stub for scripts/agent_call.py (US1)
│   └── vault_factory.py            # Builds minimal-realistic vaults on tmp_path
├── pipeline/
│   ├── test_full_cycle_e2e.py      # NEW — tier-4 single-cycle scenarios (US2)
│   └── test_multi_cycle_e2e.py     # NEW — tier-5 multi-cycle scenarios (US3)
└── fixtures/
    └── stubs/
        └── claude                  # EXISTING — grandfathered, replaced by fake_agent.py later

docs/
└── testing-strategy.md             # NEW — tier taxonomy + decision tree (US5)

build.sh                            # MODIFIED — smoke gate before wheel build (US4)
pyproject.toml                      # MODIFIED — register @pytest.mark.e2e
CLAUDE.md                           # MODIFIED — reference docs/testing-strategy.md
```

**Files NOT touched** by this feature:
- Everything under `src/research_vault/` (production code is the subject of new tests, not modified by them).
- Existing test files (grandfathered; new convention applies to new tests only).
- `dist-templates/`, `.specify/`, `.agents/`.

## Phase 0 — Research & Design

**Research deliverables** (already complete in spec.md § Clarifications):
- Approach selection (A/B/C) → **B** (layered with reusable fakes).
- Release gate strictness → **hard gate in build.sh**.
- Real LLM calls in any tier → **no**.

**Open design questions** to resolve before Phase 1:
1. Fake-agent contract format → see `contracts/fake-agent.contract.md` (Phase 1 deliverable).
2. How the fake agent parses batch prompts — regex against the `## Batch topics (JSON)` markdown block (cycle_runner.py:575) or a structured side-channel? → **Regex against the markdown block**, because the contract between cycle_runner and agent_call.py IS the prompt text. Testing through a side-channel would let real bugs in the prompt-rendering code escape. (Decision recorded here, not re-litigated in tasks.md.)
3. How to install the fake `agent_call.py` into a temp vault — copy or symlink? → **Copy**. Symlinks confuse `subprocess.run` resolution on macOS in some configurations.
4. Vault-factory scope — minimal (just enough to run a cycle) or full-fidelity (matches what `cli.generate` produces)? → **Full-fidelity**, generated by running the actual `scaffold + render_all + copy_scripts` chain. Anything less risks the same "tests vs reality" drift the existing e2e test suffers from.

## Phase 1 — Contracts & Test Skeletons (TDD RED)

**Deliverable**: every new test file exists, named scenarios are stubbed with `assert False`, and the build can compile (i.e. imports resolve) but the e2e tier is RED.

Specific RED-first commitments:
- `tests/_helpers/fake_agent.py` — module exists with `def write_scout(...)`, `def process_batch(...)`, `def main(argv: list[str]) -> int` signatures, but each raises `NotImplementedError`. A round-trip test in `tests/_helpers/test_fake_agent_contract.py` documents the expected behavior and is RED.
- `tests/_helpers/vault_factory.py` — module exists with `def build_minimal_vault(tmp_path: Path, **kw) -> Path` signature, raises `NotImplementedError`. Round-trip test asserts produced vault passes `validate_vault.py` and is RED.
- `tests/pipeline/test_full_cycle_e2e.py` — five `def test_*` functions matching spec § US2 § Acceptance Scenarios, every body is `assert False, "PENDING IMPLEMENTATION"`. Test runs at "5 failed".
- `tests/pipeline/test_multi_cycle_e2e.py` — three `def test_*` functions matching spec § US3 § Acceptance Scenarios, every body is `assert False`.
- `contracts/fake-agent.contract.md` — written, lists every input flag the fake must accept and every output artefact it must produce.

After Phase 1 the `pytest tests/_helpers tests/pipeline/test_full_cycle_e2e.py tests/pipeline/test_multi_cycle_e2e.py` command produces a known-RED report that subsequent phases turn GREEN.

## Phase 2 — Implementation (TDD GREEN)

**Order matters.** Each step depends on the prior one being GREEN:

1. **`fake_agent.py` core** — implement `write_scout` and `process_batch`. Round-trip test goes GREEN.
2. **`vault_factory.py`** — implement `build_minimal_vault`. Its round-trip test goes GREEN.
3. **US2 e2e scenarios** — implement the five tier-4 scenarios one at a time, each turning a single `assert False` into a real assertion. Order: happy path → asymmetric tail → empty scout → corrupted skill → SG failure. Any scenario that fails on first GREEN attempt reveals a real production bug; that bug is fixed in a separate commit (or, for known-already-fixed bugs like 0.2.22, just locked as a regression test).
4. **US3 e2e scenarios** — implement the three tier-5 scenarios.
5. **US4 build.sh gate** — modify `build.sh` to invoke the e2e tier before the wheel build, abort on non-zero exit, no `--skip-smoke` flag. Verified by deliberately breaking a test and confirming `build.sh` aborts before producing a tarball.
6. **US5 docs** — write `docs/testing-strategy.md`, reference it from `CLAUDE.md`.
7. **pyproject.toml** — register `@pytest.mark.e2e` marker so `pytest -m "not e2e"` works for the fast loop.

## Phase 3 — Validation

- Run the full test suite: `pytest tests/ -q` — must pass.
- Run the e2e tier alone: `pytest tests/pipeline/test_full_cycle_e2e.py tests/pipeline/test_multi_cycle_e2e.py -v` — every scenario GREEN.
- Run `./build.sh` against a clean tree — must succeed and produce `build/research-vault-*.tar.gz`.
- Deliberately re-introduce the 0.2.22 bug (re-tighten `BatchResult.to_dict` to `3..10`), run `./build.sh` — must abort with non-zero exit and produce no tarball.
- Revert the deliberate regression.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Fake-agent drifts from real `scripts/agent_call.py` contract | Medium | The `fake-agent.contract.md` is the binding spec; both implementations honor it. The fake's round-trip test asserts every contract item. A breaking change to the real `agent_call.py` invariably fails the e2e tier, surfacing the drift immediately. |
| Vault factory grows complex and slow | Medium | Cap each scenario's vault setup at < 1 s; if it grows past that, refactor toward shared module-scope fixtures (pytest `scope="module"`). |
| e2e tests become flaky on slow CI/macOS | Low | All tests are deterministic and offline; no race conditions, no network. Tests use `tmp_path` per-function so no shared state. |
| Hard gate blocks legitimate releases when an unrelated test is flaky | Low | The e2e tier is small (8 scenarios). If a scenario is genuinely flaky, the fix is to make it deterministic, not to lower the gate. |
| `pytest` markers cause friction for developers running unit-only loops | Low | Document the `pytest -m "not e2e"` pattern in `docs/testing-strategy.md` and `CLAUDE.md`. Default `pytest` runs everything (we want the gate to be opt-OUT, not opt-IN). |

## Open Questions for Spec Author

None. All decisions are recorded in spec.md § Clarifications and Phase 0 § Open design questions.
