---
_template_version: 1
---
# Raw Data Mirror

Offline mirror of every external artefact this vault cites. The
scout and DFS prompts call `scripts/raw_capture.py <url>` before
writing a note that references a URL; the capture lands here with
a `meta.json` sidecar recording `url`, `accessed`, `source_type`.

`scripts/vault_health.py` looks here first when an external URL
breaks — see Principle IX (Vault-First Citation) in the vault's
CLAUDE.md for why the raw mirror exists at all.

Layout: `raw_data/{year}/{month}/{slug}-{short-hash}.{ext}` plus
a sibling `meta.json` per artefact. Files in this folder are
write-once — never hand-edit; rerun `raw_capture.py` to refresh.
