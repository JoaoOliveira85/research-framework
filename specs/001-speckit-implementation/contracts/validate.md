# Contract: `speckit validate`

**Sub-command**: `speckit validate`
**Version**: v0.1+ (scripts available directly); v0.2+ (CLI sub-command)

---

## Synopsis

```
speckit validate --vault <dir> [--type <check>] [--output json|text]
```

Or directly (v0.1, before speckit CLI exists):

```
python scripts/validate_vault.py <vault-dir>
python scripts/validate_cycle.py <cycle-report.json>
python scripts/check_template_compliance.py <vault-dir>
python scripts/check_acronym_links.py <vault-dir>
```

---

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--vault` | path | Yes | — | Path to vault root directory |
| `--type` | string | No | all | Run only one check: `vault`, `cycle`, `template`, `acronym`, `metrics` |
| `--output` | string | No | text | Output format: `text` (human) or `json` (machine) |

---

## Checks Run (default: all)

| Check | Script | What it validates |
|-------|--------|-------------------|
| `vault` | `validate_vault.py` | Frontmatter completeness, summary ≤ 120 chars, source URLs, wikilink resolution, word count ≥ min |
| `template` | `check_template_compliance.py` | Section headings match `_templates/{type}.md` for each note |
| `acronym` | `check_acronym_links.py` | First occurrence of each acronym (from note titles) is wikilinked in body |
| `metrics` | `vault_metrics.py` | Snapshot output: note count by type, word count distribution, unresolved wikilinks count |

Note: `validate_cycle.py` is called by `run_cycle.sh`, not by `speckit validate` — it
validates individual cycle reports, not the vault itself.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | One or more violations found (structural: fixable, can proceed with caution) |
| 2 | Abort: input invalid (vault directory not found, template missing, broken JSON) |

---

## Output Format (text, exit 1 example)

```
FAIL  data_vault/01 - Concepts/Long Summary.md
      summary: 125 chars (limit: 120)

FAIL  data_vault/01 - Concepts/Missing Source.md
      source_urls: empty (at least one required)

FAIL  data_vault/02 - Services/Payment Service.md
      related: [[Settlement Flow]] — file not found

3 violations found. Fix before proceeding to Phase 3.
```

---

## Output Format (json, exit 1 example)

```json
{
  "exit_code": 1,
  "violations": [
    {
      "file": "data_vault/01 - Concepts/Long Summary.md",
      "field": "summary",
      "message": "125 chars (limit: 120)"
    }
  ],
  "summary": "3 violations found"
}
```

---

## Error Cases

| Condition | Exit | Output |
|-----------|------|--------|
| `--vault` path does not exist | 2 | "vault directory not found: {path}" |
| `_templates/` directory missing | 2 | "template directory not found: {path}/_templates" |
| Note has unknown `type` (no template) | 1 | "unknown note type: {type} in {file}" |
| Malformed YAML frontmatter | 2 | "YAML parse error in {file}: {error}" |
