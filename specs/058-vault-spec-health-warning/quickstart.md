# Quickstart: 058 Control-File Git Tracking Warning

## Reproduce untracked warning (US1)

```bash
cd /tmp && rm -rf v058-demo && mkdir v058-demo && cd v058-demo
git init -q
mkdir -p _pipeline data_vault
echo "# spec" > research.spec.md
echo "stages: {}" > settings.yaml
echo "# backlog" > _pipeline/research-backlog.md
echo '{}' > _pipeline/coverage-targets.json
# deliberate: do NOT git add research.spec.md

python /path/to/research-framework/scripts/vault_health.py . --offline
# Expect report section "## Control-file git tracking" with:
#   - WARN UNTRACKED research.spec.md
# Exit code 0 if wikilinks/URLs/templates are otherwise clean (advisory only).

git add research.spec.md settings.yaml _pipeline/
python .../vault_health.py . --offline
# Tracking warnings for added files clear.
```

## Reproduce ignored warning (SC-004)

```bash
echo "settings.yaml" >> .gitignore
git add .gitignore settings.yaml
git commit -qm "ignore settings"
python .../vault_health.py . --offline
# Expect: WARN IGNORED settings.yaml
```

## Non-git vault (US2)

```bash
cd /tmp/nogit-vault && mkdir -p _pipeline && echo "# x" > research.spec.md
python .../vault_health.py . --offline
# No control-file-tracking warnings; section shows skip or no WARN lines.
```

## Regression suite

```bash
pytest tests/scripts/test_vault_health.py::TestControlFileGitTracking -v
pytest tests/scripts/test_vault_health.py -v   # full module — prior tests unchanged
```
