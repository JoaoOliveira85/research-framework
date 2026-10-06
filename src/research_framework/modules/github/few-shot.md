# GitHub module schema examples

Calibration examples for per-vault schema-gen. These teach the model that
GitHub fact buckets should be domain-driven (driven by the vault's
`research.spec.md`), not hard-coded. The `github` module surfaces remote
activity (PRs / issues / releases); `code` (a separate module) surfaces local
working-copy signals.

## Example: AI / ML tooling vault

```json
{
  "type": "object",
  "properties": {
    "release_tags": {"type": "array", "items": {"type": "string"}},
    "notable_prs": {"type": "array", "items": {"type": "string"}},
    "open_issues_themes": {"type": "array", "items": {"type": "string"}},
    "maintainers": {"type": "array", "items": {"type": "string"}}
  }
}
```

## Example: platform / infrastructure vault

```json
{
  "type": "object",
  "properties": {
    "breaking_changes": {"type": "array", "items": {"type": "string"}},
    "deprecations": {"type": "array", "items": {"type": "string"}},
    "security_advisories": {"type": "array", "items": {"type": "string"}},
    "release_cadence": {"type": "string"}
  }
}
```
