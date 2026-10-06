# YouTube module schema examples

Calibration examples for per-vault schema-gen. These teach the model
that YouTube fact buckets should be domain-driven (driven by the
vault's `research.spec.md`), not hard-coded.

## Example: web-engineering vault

```json
{
  "type": "object",
  "properties": {
    "technologies": {"type": "array", "items": {"type": "string"}},
    "patterns": {"type": "array", "items": {"type": "string"}},
    "opinions": {"type": "array", "items": {"type": "string"}},
    "video_topic": {"type": "string"}
  }
}
```

## Example: AI/ML research vault

```json
{
  "type": "object",
  "properties": {
    "research_directions": {"type": "array", "items": {"type": "string"}},
    "model_families": {"type": "array", "items": {"type": "string"}},
    "papers_referenced": {"type": "array", "items": {"type": "string"}},
    "video_topic": {"type": "string"}
  }
}
```

## Example: biology / life-sciences vault

```json
{
  "type": "object",
  "properties": {
    "organisms": {"type": "array", "items": {"type": "string"}},
    "techniques": {"type": "array", "items": {"type": "string"}},
    "open_questions": {"type": "array", "items": {"type": "string"}},
    "video_topic": {"type": "string"}
  }
}
```
