# Quickstart: Vault output integrity on constrained exit

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

Reproduce each rc1 defect and confirm the fix. Assumes a dev checkout
(`pip install -e .`) of branch `062-vault-output-integrity`.

## FR1 — rejected notes are quarantined, not indexed

```bash
# Construct a vault with a note stamped verifier_status: rejected, then finalise.
# (test_rejected_note_handling.py builds this; manual repro sketch:)
printf -- '---\nverifier_status: rejected\nverifier_notes: ["claims X unverified"]\n---\nbody\n' \
  > /tmp/vault/data_vault/concepts/bad-note.md

research-framework reindex --vault /tmp/vault   # rebuild Layer-1 index
# BEFORE fix: bad-note.md is in _index.md and /ask can cite it.
# AFTER fix (on finalise): bad-note.md is moved to _pipeline/quarantine/,
#   _index.md does NOT list it, /ask cannot cite it, and:
grep -i 'rejected' /tmp/vault/_pipeline/run-report.md
# EXPECT: "Verifier: 1 notes ended the run rejected and were quarantined"
ls /tmp/vault/_pipeline/quarantine/      # EXPECT: bad-note.md present
grep bad-note /tmp/vault/_pipeline/research-backlog.md   # EXPECT: a rewrite pointer
```

## FR2 — no duplicate files; one commit per cycle; nothing untracked

```bash
# A re-emit of an existing note must overwrite, never fork to "... 2.md".
research-framework cycle --vault /tmp/vault   # write cycle N
# simulate a same-cycle metadata correction re-emit, then:
git -C /tmp/vault log --oneline | grep -c 'research: cycle'   # EXPECT: one per cycle
git -C /tmp/vault status --porcelain data_vault/             # EXPECT: empty (no untracked)
ls /tmp/vault/data_vault/**/*' 2.md' 2>/dev/null             # EXPECT: nothing

scripts/validate_vault.py /tmp/vault
# EXPECT: no " N.md"/content-hash duplicate findings.
```

## FR3 — acronym wikilinks resolve

```bash
# A note titled "Order Engine Customer Data Handler" with [[OECDH]] refs elsewhere.
research-framework cycle --vault /tmp/vault    # cycle-end wikilink pass runs
grep -r 'OECDH' /tmp/vault/data_vault/
# EXPECT: [[OECDH]] either rewritten to the canonical stem OR resolving to a
#         generated redirect stub data_vault/.../OECDH.md (note_type: alias).
scripts/validate_vault.py /tmp/vault ; echo "exit=$?"
# EXPECT: exit 0 for the dead-acronym-link class (other classes may still report).
```

## Done-when

- `pytest tests/pipeline/test_rejected_note_handling.py
  tests/pipeline/test_no_duplicate_notes.py
  tests/pipeline/test_vault_commit_no_untracked.py
  tests/pipeline/test_acronym_alias_coverage.py
  tests/scripts/test_validate_vault_integrity.py` all green.
- A constrained-exit run leaves 0 indexed rejected notes, 0 ` N.md` forks, 0
  untracked `data_vault/` content, and 0 dangling acronym links (SC-001/002/003).
- `./build.sh --quality` shows no baseline movement (alias stubs excluded from
  metrics per data-model.md Entity 4).
