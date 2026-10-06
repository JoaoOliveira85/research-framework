# Quickstart — Spec 024 Testing Infrastructure v2

**Branch**: `024-testing-infrastructure-v2`
**Status**: Phase 1 (Design & Contracts) — produced by `/speckit.plan`
**Audience**: the engineer (or future agent) implementing spec 024's
seven user stories. Each section is a self-contained iteration loop
keyed to one user story.

This is **not** a tutorial — it assumes familiarity with the repo
layout, `pytest`, and the spec-kit flow. Use it as a check-list.

---

## 0. Bootstrap

```bash
# From the worktree root:
.venv/bin/pytest -m "not e2e" -q --tb=line   # baseline (expect ~1156 passed, 2 skipped)
.venv/bin/ruff check .                       # baseline (expect zero errors)
./build.sh                                   # smoke gate (expect green)
```

If any of these three is red, **stop**. Fix the baseline before
touching 024 work. Spec 024's success criteria (SC-001, SC-003)
require all three green at ship.

---

## 1. US1 — LLM dispatch guard

**Goal**: `tests/_helpers/test_llm_dispatch_guard.py` runs in tier
2, catches `subprocess.run(["claude", ...])` and
`subprocess.run(["codex", ...])` anywhere under
`src/research_framework/`, and tolerates the two-entry allowlist
in `tests/_helpers/llm_dispatch_allowlist.yaml`.

### Dev loop

```bash
# 1. Add a deliberate bypass to confirm the guard fires.
echo 'import subprocess; subprocess.run(["claude", "--print"])' \
    >> src/research_framework/pipeline/_scratch_violation.py

.venv/bin/pytest tests/_helpers/test_llm_dispatch_guard.py -q
# Expect: FAILED with file + line + remediation message.

rm src/research_framework/pipeline/_scratch_violation.py

.venv/bin/pytest tests/_helpers/test_llm_dispatch_guard.py -q
# Expect: PASSED (only the two allowlisted entries remain).
```

### Reference

- Contract: `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`
- Allowlist shape: [data-model.md § Entity 1](./data-model.md#entity-1--llm-dispatch-allowlist-entry-tests_helpersllm_dispatch_allowlistyaml)
- Parser strategy: [research.md § Decision 2](./research.md#decision-2--lint-guard-parser-strategy) (Python `ast`, not regex)

---

## 2. US2 — Fake-agent stage extensions

**Goal**: `verifier`, `narrator`, and `probe_retrieval` stages emit
deterministic per-scenario responses. Five scenarios at ship
(verifier × 3, narrator × 1, probe_retrieval × 1).

### Dev loop

```bash
# 1. Write a scenario JSON.
cat > tests/_helpers/fake_agent_scenarios/verifier/accept.json <<'EOF'
{"verdict": "accept", "violations": [], "suggested_fix": null}
EOF

# 2. Extend fake_agent.py's main() to dispatch verifier → handler that reads the file.

# 3. Add a contract test:
#    test_verifier_accept_emits_canonical_verdict() in tests/_helpers/test_fake_agent_contract.py.

.venv/bin/pytest tests/_helpers/test_fake_agent_contract.py -q
# Expect: PASSED with the new test included.

# 4. Repeat for reject, malformed_json, narrator/happy, probe_retrieval/happy.
```

### Reference

- Authoritative contract: `specs/018-testing-strategy/contracts/fake-agent.contract.md` (v2)
- Implementation tracker: [contracts/fake-agent-v2-stage-extensions.contract.md](./contracts/fake-agent-v2-stage-extensions.contract.md)
- Scenario file shape: [data-model.md § Entity 2](./data-model.md#entity-2--fake-agent-scenario-response-json-files)
- Determinism rules: research.md § Decision 5 + 018 contract § Determinism guarantee

---

## 3. US3 — Smoke meta-tests restored

**Goal**: `tests/build/test_install_wizard_skip_redundant_questions.py`
and `tests/build/test_smoke_gate_enforces_contract_tier.py` run as
part of `./build.sh` and pass.

### Dev loop

```bash
# 1. Verify the files still exist (they do as of 2026-05-21):
ls tests/build/test_install_wizard_skip_redundant_questions.py
ls tests/build/test_smoke_gate_enforces_contract_tier.py

# 2. Run them locally before flipping build.sh:
.venv/bin/pytest tests/build/ -q
# Expect: green. If red, debug before proceeding — flipping the comment
# while the tests are red ships a broken smoke gate.

# 3. Uncomment build.sh lines 74-75 (the two SMOKE_TESTS entries).

# 4. Run the smoke gate:
./build.sh
# Expect: green, both new test names appearing in pytest output.
```

### Reference

- Smoke manifest shape: build.sh lines 30-76
- ADR-0007 (smoke gate is mandatory, no `--skip-smoke` flag)
- spec 019 § US1 (smoke-gate enforcer)

---

## 4. US4 — Spec acceptance-coverage lint guard + FR-013 backfill

**Goal**: `tests/spec/test_acceptance_coverage_guard.py` runs in tier
2 and fails on any spec.md with G/W/T scenarios but no `##
Acceptance coverage` section. Three existing specs (015a, 017, 018)
gain the section in the same PR.

### Dev loop

```bash
# 1. Write the guard. See contracts/acceptance-coverage-guard.contract.md
#    for the spec-discovery + structure regex.

.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q
# Expect on first run: FAILED (015a / 017 / 018 missing the section).

# 2. Backfill 015a/017/018. For each:
#    - Open specs/<dir>/spec.md
#    - Add `## Acceptance coverage` near the end (per data-model.md § Entity 5)
#    - Map every G/W/T user story to a row whose evidence cell matches
#      one of the four allowed forms (data-model.md § Entity 3)

# 3. Re-run:
.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q
# Expect: PASSED (no allowlist, no exceptions).

# 4. Self-dogfood check: does this spec (024) itself pass?
.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q -k "024"
# Expect: PASSED.
```

### Reference

- Contract: [contracts/acceptance-coverage-guard.contract.md](./contracts/acceptance-coverage-guard.contract.md)
- Row evidence forms: [data-model.md § Entity 3](./data-model.md#entity-3--acceptance-coverage-row-markdown-table-cell)
- Per-spec backfill sketch: [research.md § Decision 3](./research.md#decision-3--backfill-mechanics-for-fr-013-acceptance-coverage-on-015a--017--018)

---

## 5. US5 — CHANGELOG regression-link lint guard + FR-014 backfill

**Goal**: `tests/spec/test_changelog_regression_links.py` runs in
tier 2 and fails on any released-version `### Fixed` bullet missing
an annotation. All 15 released-version `### Fixed` sections in
`CHANGELOG.md` are backfilled in the same PR.

### Dev loop

```bash
# 1. Write the guard. See contracts/changelog-regression-guard.contract.md
#    for the state-machine layout.

.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q
# Expect on first run: FAILED on ~30-50 bullets (every released-version
# `### Fixed` bullet without an annotation).

# 2. Backfill. For each `### Fixed` block:
#    - Read the bullet.
#    - git log --follow on the file the bullet mentions (if any) to find the
#      sibling test commit.
#    - Annotate with `(test: <path>::<name>)`, `(regression test: …)`, or
#      `(no test: <one-line rationale>)` per research.md § Decision 4.

# 3. Re-run:
.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q
# Expect: PASSED.

# 4. Cross-check FR-015: any `(test: …)` annotation that points at
#    tests/pipeline/test_e2e_synthetic_vault.py must be re-pointed to a
#    tier-5 scenario in tests/integration/test_cycle_e2e.py. The
#    path-existence check enforces this naturally — re-run after US7's
#    deletion and confirm zero failures.
```

### Reference

- Contract: [contracts/changelog-regression-guard.contract.md](./contracts/changelog-regression-guard.contract.md)
- Annotation regex: [data-model.md § Entity 4](./data-model.md#entity-4--changelog--fixed-annotation-regex-shape)
- Backfill mechanics: [research.md § Decision 4](./research.md#decision-4--backfill-mechanics-for-fr-014-changelog-annotations)

---

## 6. US6 — Tier-5 e2e wires three new scenarios

**Goal**: `tests/integration/test_cycle_e2e.py` gains three new
test functions (`oos_topic`, `partial_yield`, `verifier_reject`),
each driven by `vault_factory.build_minimal_vault` +
`fake_agent.install_shim` + scenario env-vars.

### Dev loop

```bash
# 1. Sketch one scenario first (e.g. verifier_reject):
#    @pytest.mark.e2e
#    def test_cycle_verifier_reject_moves_note_to_rejected(tmp_path, monkeypatch):
#        vault = vault_factory.build_minimal_vault(tmp_path, ...)
#        monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "reject")
#        run_cycle(vault, cycle=1)
#        assert (vault / "_pipeline" / "rejected").exists()
#        # ...

.venv/bin/pytest tests/integration/test_cycle_e2e.py -q -m e2e
# Expect: PASSED for the one new scenario.

# 2. Repeat for oos_topic and partial_yield.

# 3. Confirm the fast loop is unaffected:
.venv/bin/pytest -m "not e2e" -q
# Expect: same count as baseline + new lint guard tests (still under SC-002's <30s delta).
```

### Reference

- Test-function sketches: [data-model.md § Entity 8](./data-model.md#entity-8--tier-5-e2e-scenarios-new-test-cases-in-testsintegrationtest_cycle_e2epy)
- Vault factory contract: `specs/018-testing-strategy/contracts/vault-factory.contract.md`
- Fake-agent scenario selection: 018 § Scenario selection

---

## 7. US7 — Delete `tests/pipeline/test_e2e_synthetic_vault.py`

**Goal**: the file no longer exists; coverage flows via US6's tier-5
scenarios.

### Dev loop

```bash
# 1. Confirm US6's three scenarios are green (otherwise the deletion
#    drops coverage):
.venv/bin/pytest -m e2e -q -k "oos_topic or partial_yield or verifier_reject"
# Expect: 3 PASSED.

# 2. Delete:
rm tests/pipeline/test_e2e_synthetic_vault.py

# 3. Confirm no orphan imports / fixture-dependencies:
.venv/bin/pytest -m "not e2e" --collect-only -q | grep -i error
# Expect: no errors.

# 4. Run the FR-015 cross-check: any CHANGELOG `(test: …)` annotation
#    pointing at the deleted file is caught by the US5 guard's
#    path-existence check. Fix by re-pointing to the equivalent US6
#    scenario.
```

---

## 8. Final ship checklist

Before opening the PR (or running `/speckit.tasks` to enumerate
remaining work):

- [ ] **SC-001**: `pytest` full sweep green (`pytest`).
- [ ] **SC-002**: fast loop runtime delta < 30 s vs the pre-024
      baseline (`pytest -m "not e2e"` — note the wall-clock).
- [ ] **SC-003**: `./build.sh` smoke green, including the two QW-2
      meta-tests.
- [ ] **SC-004**: `tests/_helpers/llm_dispatch_allowlist.yaml` contains
      exactly two entries.
- [ ] **SC-005**: every existing spec passes the acceptance-coverage
      guard with no allowlist.
- [ ] **SC-006**: every released-version `### Fixed` bullet has an
      annotation; no allowlist.
- [ ] **SC-007**: `tests/pipeline/test_e2e_synthetic_vault.py` does not exist.
- [ ] **SC-008**: every Phase 2 checkbox in
      `docs/testing-strategy.md` § Phase 2 implementation checklist
      is ticked off.
- [ ] **SC-009**: this spec's own `## Acceptance coverage` section
      passes the FR-006 guard.
- [ ] **SC-010**: 015a/017/018 have populated `## Acceptance coverage`
      sections.
- [ ] **SC-011**: every `(no test: …)` annotation carries a rationale.
- [ ] **SC-012**: no annotation points at the deleted synthetic-vault
      test path.
- [ ] **FR-011**: `docs/testing-strategy.md` line 38 says
      `024-testing-infrastructure-v2`, NOT
      `refactor/testing-strategy-phase2`.
- [ ] **Doc-update checklist** (CLAUDE.md `/speckit.plan` stage):
      ROADMAP / TODO updated if scope shifted; ADRs written if any
      net-new architectural decisions were committed. *(None
      anticipated at clarify time — research.md decisions are
      mechanics, not architecture.)*

---

## Anti-patterns to avoid

- **Adding scenarios to `fake_agent.py` without contract tests.** The
  Discovery convention in
  [contracts/fake-agent-v2-stage-extensions.contract.md](./contracts/fake-agent-v2-stage-extensions.contract.md) §
  Discovery convention rejects this — every scenario JSON MUST have a
  matching test function.
- **Adding allowlist rows to the new acceptance-coverage or
  CHANGELOG-regression guards.** Q4 and Q5 ratifications are
  "no allowlist". If a real edge case appears, the right answer is
  a new evidence form (acceptance-coverage) or a new annotation
  form (CHANGELOG) via ADR — not an allowlist.
- **Re-introducing the bespoke mock pattern from
  `test_e2e_synthetic_vault.py`** in the new tier-5 scenarios. They
  MUST use `vault_factory.build_minimal_vault` +
  `fake_agent.install_shim` exclusively.
- **Editing `CHANGELOG.md` `[Unreleased]` block bullets without an
  annotation** *just because the guard skips that block*. The
  annotation is required by release time — adding it at write time
  costs nothing and prevents the future "wait, what tests
  this?" scramble.
