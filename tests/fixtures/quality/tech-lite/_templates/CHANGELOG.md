---
title: "Template Changelog"
type: meta
updated: 2026-05-21
---

# Template Changelog

Tracks changes to this vault's note templates. When a template changes,
notes rendered from older versions can be detected by comparing their
frontmatter ``template_version`` against the current version listed
below.

`scripts/vault_health.py --check-template-version` reads this table and
reports (or, with `--apply`, upgrades) notes whose stamp is out of date.

## Current Versions

| Template | Version | Last Changed | Notes |
|----------|---------|-------------|-------|
| service.md | 1.0.0 | 2026-05-21 | Initial version |
| flow.md | 1.0.0 | 2026-05-21 | Initial version |
| concept.md | 1.0.0 | 2026-05-21 | Initial version |
| decision.md | 1.0.0 | 2026-05-21 | Initial version |

## Version History

Hand-edit this section when you change a template in ``_templates/``.
Use SemVer: MINOR for additive changes (new section, new optional key),
MAJOR for renames/removals that break existing notes.

### service.md

#### 1.0.0 (2026-05-21)
- Initial template for ``service`` notes.

### flow.md

#### 1.0.0 (2026-05-21)
- Initial template for ``flow`` notes.

### concept.md

#### 1.0.0 (2026-05-21)
- Initial template for ``concept`` notes.

### decision.md

#### 1.0.0 (2026-05-21)
- Initial template for ``decision`` notes.
