# Contracts — Feature 018 (Layered Testing Strategy)

Binding contracts between the new test infrastructure (`tests/_helpers/`) and the
production code it exercises. Each contract is the authoritative specification
for one shared artefact.

## Contracts in this directory

| File | Subject | Consumed by |
|------|---------|-------------|
| `fake-agent.contract.md` | CLI + I/O contract for `tests/_helpers/fake_agent.py` (the test-only stub for `scripts/agent_call.py`). | US1 (T007–T012), US2 (T013–T020), US3 (T021–T024). |
| `vault-factory.contract.md` | Python API + post-conditions for `tests/_helpers/vault_factory.py` (the temp-vault builder). | US2 (T013–T020), US3 (T021–T024). |

## How to use these contracts

1. **When adding a fake-agent scenario**: edit `fake-agent.contract.md` first (add the scenario name to § Scenarios), then implement it in `tests/_helpers/fake_agent.py`, then add a contract test in `tests/_helpers/test_fake_agent_contract.py`.
2. **When extending vault layout**: edit `vault-factory.contract.md` first (extend § Post-Conditions), then update `tests/_helpers/vault_factory.py`, then update `tests/_helpers/test_vault_factory_contract.py`.
3. **A contract change without an implementation change (or vice versa) is a bug.** The two-way binding is enforced by the contract test files.
