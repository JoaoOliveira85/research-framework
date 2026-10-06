---
vault_name: benchmark-fixture
topic: "Frozen benchmark vault for the executor × model harness (spec 056)"
note_types:
  - concept
search_dimensions:
  - technical
---

# Benchmark Fixture Vault

This is a **frozen, data-only** fixture for the spec-056 executor × model
benchmarking harness. It is never run as a real research vault; it only supplies
stable per-task inputs (`tasks/`), a note template (`_templates/`), and recorded
hermetic responses (`fake_agent_responses/`) so the harness can be exercised
without any live LLM call.

Do not edit the recorded responses or the manifest without updating the
spec-056 contract tests — the hermetic quality scores are pinned against them.
