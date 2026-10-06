# Quickstart: Cycle-budget configuration consolidation

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

How to exercise each FR end-to-end and confirm the rc1 truncation is now loud +
recorded. Assumes a dev checkout (`pip install -e .`) of branch `061-cycle-budget-config`.

## Reproduce the rc1 root cause (pre-fix behaviour, for reference)

The codebase-vault rc1 bundle carried `pipeline.max_cycles: 20` **and**
`cycles.initial_max: 6`. The generate path read the latter, mutated the spec, and
printed one line:

```
[phase 0] cycles.initial_max from settings: 6 (was 12)
```

…then exited `constrained — max_cycles (6) reached` at half the spec's 12-cycle ask,
with no WARNING and no run-report provenance.

## FR1 — canonical key + deprecation WARNING

```bash
# settings carries ONLY the deprecated key
printf 'pipeline:\n  budget_usd: 50\ncycles:\n  initial_max: 6\n' > /tmp/s.yaml
research-framework parse-spec ... --settings /tmp/s.yaml   # or a dry generate
# EXPECT: one logging.WARNING naming pipeline.max_cycles and stating it honoured 6
#         as an alias; effective max_cycles == 6.
```

```bash
# canonical wins when both present
printf 'pipeline:\n  max_cycles: 12\ncycles:\n  initial_max: 6\n' > /tmp/s.yaml
# EXPECT: effective max_cycles == 12; WARNING that cycles.initial_max is deprecated
#         and was NOT used (pipeline.max_cycles wins).
```

## FR2 — spec schema no longer carries the budget

```bash
# a spec with a stray budget block parses fine and the value has no effect
cat > /tmp/spec.md <<'EOF'
---
name: demo
budget:
  max_cycles: 999
  max_usd: 999
pizza: pepperoni
---
EOF
research-framework parse-spec /tmp/spec.md
# EXPECT: parses OK; max_cycles:999 / max_usd:999 ignored exactly like `pizza`.
#         Effective budget comes from settings/flag/default, never 999.
```

## FR3 — `--max-cycles` is the last word

```bash
# flag beats settings beats default
research-framework generate /tmp/vault --settings /tmp/s.yaml --max-cycles 3
# EXPECT: effective max_cycles == 3 regardless of settings; source == "flag".
research-framework generate /tmp/vault --max-cycles 0
# EXPECT: exit 2, clear "must be a positive integer" message.
```

## FR4 — overrides are LOUD and recorded

```bash
research-framework generate /tmp/vault --settings /tmp/s.yaml 2>run.log
# EXPECT: the override is a WARNING record (suppressible with --log-level error),
#         NOT a bare print.
research-framework generate /tmp/vault --log-level error 2>quiet.log
grep -i 'cycles' quiet.log    # EXPECT: no override line at error level
```

After a constrained run, inspect the report:

```bash
cat /tmp/vault/_pipeline/run-report.md | grep -i 'Cycle budget'
# EXPECT: "Cycle budget: 6 (source: settings) — ran 6 — exit: constrained (max_cycles reached)"
jq '.cycle_budget' /tmp/vault/_pipeline/run-report.json
# EXPECT: {configured, source, actual, exit_status:"constrained"} with actual==configured
```

## FR5 — seeds agree; baselines hold

```bash
grep -n max_cycles settings.yaml settings.codex.yaml   # EXPECT: one canonical value, no disagreement
./build.sh --quality                                   # EXPECT: 3 fixtures, 0 baseline movement
```

## Done-when

- All FR tests green (`pytest tests/cli/test_budget_resolver.py
  tests/cli/test_max_cycles_flag.py tests/pipeline/test_cycle_budget_settings.py
  tests/pipeline/test_run_report_budget_provenance.py
  tests/spec/test_schema_budget_removed.py`).
- `./build.sh --quality` shows no unintended baseline movement.
- Re-running the rc1 codebase-vault scenario surfaces the truncation as a WARNING +
  run-report `cycle_budget`, not a buried print (SC-002).
