# O'Reilly module schema examples

Calibration examples for per-vault schema-gen. These teach the model
that O'Reilly fact buckets should be domain-driven (driven by the vault's
`research.spec.md`), not hard-coded.

## Example: AI / ML engineering vault

```json
{
  "type": "object",
  "properties": {
    "technologies": {"type": "array", "items": {"type": "string"}},
    "concepts": {"type": "array", "items": {"type": "string"}},
    "authors": {"type": "array", "items": {"type": "string"}},
    "content_types": {"type": "array", "items": {"type": "string"}},
    "skill_levels": {"type": "array", "items": {"type": "string"}}
  }
}
```

## Example: platform / DevOps vault

```json
{
  "type": "object",
  "properties": {
    "platforms": {"type": "array", "items": {"type": "string"}},
    "tools": {"type": "array", "items": {"type": "string"}},
    "certification_paths": {"type": "array", "items": {"type": "string"}},
    "learning_paths": {"type": "array", "items": {"type": "string"}}
  }
}
```

## Example: certification prep vault

```json
{
  "type": "object",
  "properties": {
    "topics": {"type": "array", "items": {"type": "string"}},
    "book_titles": {"type": "array", "items": {"type": "string"}},
    "course_formats": {"type": "array", "items": {"type": "string"}},
    "difficulty_tier": {"type": "string"}
  }
}
```
