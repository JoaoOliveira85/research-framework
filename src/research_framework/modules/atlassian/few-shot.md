# Atlassian module schema examples

Calibration examples for per-vault schema-gen. These teach the model that
Atlassian fact buckets should be domain-driven (driven by the vault's
`research.spec.md`), not hard-coded. The module covers two surfaces — Jira
issues and Confluence pages — so buckets often mix delivery + knowledge facets.

## Example: product / delivery vault

```json
{
  "type": "object",
  "properties": {
    "epics": {"type": "array", "items": {"type": "string"}},
    "in_progress_issues": {"type": "array", "items": {"type": "string"}},
    "blocked_issues": {"type": "array", "items": {"type": "string"}},
    "owners": {"type": "array", "items": {"type": "string"}}
  }
}
```

## Example: knowledge-base / docs vault

```json
{
  "type": "object",
  "properties": {
    "decisions": {"type": "array", "items": {"type": "string"}},
    "runbooks": {"type": "array", "items": {"type": "string"}},
    "recently_updated_pages": {"type": "array", "items": {"type": "string"}},
    "spaces": {"type": "array", "items": {"type": "string"}}
  }
}
```
