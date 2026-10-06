# RSS module schema examples

Calibration examples for per-vault schema-gen. These teach the model
that RSS fact buckets should be domain-driven (driven by the vault's
`research.spec.md`), not hard-coded.

## Example: AI newsletters / industry news vault

```json
{
  "type": "object",
  "properties": {
    "topics": {"type": "array", "items": {"type": "string"}},
    "companies_mentioned": {"type": "array", "items": {"type": "string"}},
    "authors": {"type": "array", "items": {"type": "string"}},
    "publication_dates": {"type": "array", "items": {"type": "string"}},
    "headline_theme": {"type": "string"}
  }
}
```

## Example: engineering / tools blog vault

```json
{
  "type": "object",
  "properties": {
    "tools": {"type": "array", "items": {"type": "string"}},
    "techniques": {"type": "array", "items": {"type": "string"}},
    "code_patterns": {"type": "array", "items": {"type": "string"}},
    "article_angle": {"type": "string"}
  }
}
```

## Example: research / preprint feed vault

```json
{
  "type": "object",
  "properties": {
    "paper_titles": {"type": "array", "items": {"type": "string"}},
    "arxiv_ids": {"type": "array", "items": {"type": "string"}},
    "research_areas": {"type": "array", "items": {"type": "string"}},
    "feed_category": {"type": "string"}
  }
}
```
