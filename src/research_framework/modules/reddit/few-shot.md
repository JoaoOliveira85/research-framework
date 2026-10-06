# Reddit module schema examples

Calibration examples for per-vault schema-gen. These teach the model
that Reddit fact buckets should be domain-driven (driven by the
vault's `research.spec.md`), not hard-coded.

## Example: AI trends / industry news vault

```json
{
  "type": "object",
  "properties": {
    "trends": {"type": "array", "items": {"type": "string"}},
    "products_mentioned": {"type": "array", "items": {"type": "string"}},
    "sentiment_signals": {"type": "array", "items": {"type": "string"}},
    "post_topic": {"type": "string"}
  }
}
```

## Example: developer tools / workflows vault

```json
{
  "type": "object",
  "properties": {
    "tools": {"type": "array", "items": {"type": "string"}},
    "workflows": {"type": "array", "items": {"type": "string"}},
    "pain_points": {"type": "array", "items": {"type": "string"}},
    "discussion_theme": {"type": "string"}
  }
}
```

## Example: research / papers vault

```json
{
  "type": "object",
  "properties": {
    "papers_referenced": {"type": "array", "items": {"type": "string"}},
    "methods": {"type": "array", "items": {"type": "string"}},
    "open_questions": {"type": "array", "items": {"type": "string"}},
    "subreddit_context": {"type": "string"}
  }
}
```
