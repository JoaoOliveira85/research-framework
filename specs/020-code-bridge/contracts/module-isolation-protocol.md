# Module Isolation Protocol (D9)

The modular architecture exists specifically to isolate complex,
failure-prone data-extraction flows from the main research loop. This
document specifies HOW the framework isolates a failing module-
subsystem call, retries once, salvages partial output, and continues
the cycle.

## Failure-mode taxonomy

Three categories of module-subsystem failure are covered by this
protocol:

| # | Failure | Where | Retry callable |
|---|---------|-------|----------------|
| 1 | Extractor exception | `subprocess.run(['python', 'extractor.py'])` non-zero exit, timeout, or unparseable stdout | yes (same input, same module) |
| 2 | Validator Python exception | `<module>.validators.py::validate(payload)` raises | yes (same payload, same validator) |
| 3 | Manifest parse failure | `yaml.safe_load(manifest_path)` raises or fails JSON Schema validation | yes (re-read file from disk) |

## Algorithm

```python
def isolated_call(callable, *args, source_id, source_module, kind, **kwargs):
    """Run callable with retry-once + salvage + isolation."""
    partial_output = None
    last_exc = None
    
    for attempt in (1, 2):
        try:
            return callable(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            # Salvage any partial output the callable exposes
            partial_output = getattr(exc, 'partial', None) or partial_output
            # Always log; never swallow
            log_to_bridge_log(source_id, source_module, kind, attempt, exc)
            log_to_agent_calls(source_id, source_module, kind, attempt, exc)
            if attempt == 1:
                continue  # retry
    
    # Both attempts exhausted
    if partial_output and kind == 'extractor':
        write_partial_payload(source_id, source_module, partial_output)
    mark_source_failed(source_id, source_module, kind, last_exc)
    surface_in_run_report(source_id, source_module, kind, last_exc)
    return None
```

## Per-failure-mode details

### Extractor exception (kind 1)

**Detection**:
- `subprocess.run` raises `TimeoutExpired` (extractor exceeded
  600s wall clock).
- `subprocess.run` returns non-zero exit code.
- Stdout JSON parsing fails (via `verifier._extract_json_blob`
  pattern).

**Retry**:
- Spawn a fresh subprocess with the EXACT SAME stdin payload.
- No backoff; immediate retry.

**Salvage**:
- If the extractor wrote *some* JSON to stdout before crashing, the
  framework attempts to recover. Algorithm:
  1. Strip trailing whitespace.
  2. Try `json.loads()` on progressively shorter suffix-stripped
     strings until one parses (e.g. drop final `,`, final
     incomplete `{...}`, final incomplete array, etc.).
  3. If a valid JSON object parses, treat it as a partial payload.
- Write the partial payload with `verdict: "error"`,
  `partial: true`.
- Module's stdout heartbeat status file is appended to the
  run-report's failure record.

### Validator Python exception (kind 2)

**Detection**: `<module>.validators.py::validate(payload)` raises any
exception (not just `ValidationError`).

**Retry**:
- Re-import the module (`importlib.reload`) defensively in case the
  exception was caused by stale bytecode.
- Re-call `validate(payload)` with the same payload.

**Salvage**: No salvage possible (validators are pure functions of
their input). The payload is treated as if validation failed with
the exception's message as the error.

**Note**: A validator returning a non-empty list of errors is NOT a
failure for this protocol \u2014 that's a normal "validation failed"
outcome that goes into the correction loop. Only unhandled exceptions
trigger isolation.

### Manifest parse failure (kind 3)

**Detection**:
- `yaml.safe_load()` raises `yaml.YAMLError`.
- Schema validation against `manifest.schema.json` returns errors.

**Retry**: Re-read the file from disk (defensive against transient
FS hiccups). Re-parse.

**Salvage**: No salvage. The module is excluded from the trigger
registry for this run.

**Surface**: The module's name + manifest path + error appear in the
run-report's "Module Discovery Issues" sub-section, separate from
per-source failures.

## Run-report surface

`_pipeline/cycles/cycle-NNN/run-report.md` gains a new top-level
section (after "Quality Gates", before "Token Usage"):

```markdown
## Module-Subsystem Issues

The following failures occurred this cycle. The pipeline continued;
the failures are surfaced here so you can investigate.

### Per-source failures

| Source | Module | Failure kind | Salvaged? | Log ref |
|--------|--------|--------------|-----------|---------|
| /Users/.../my-repo | code | extractor:TimeoutExpired (600s, retried, same) | partial (12 facts) | bridge.log:142 |
| https://reddit.com/r/foo | reddit | validator-py:KeyError (retried, same) | no | bridge.log:198 |

### Module discovery issues

| Module path | Failure | Excluded for this cycle? |
|-------------|---------|--------------------------|
| <vault>/modules/youtube/manifest.yaml | YAMLError: line 5 col 2 | yes |

If "Module discovery issues" is non-empty, sources matching the
excluded modules' triggers will be skipped this cycle. Fix the
manifests and re-run.
```

If both sub-sections are empty, the section header is omitted (no
noise on clean cycles).

## Logging discipline

Every isolation event logs to TWO places:

1. **`bridge.log`** (existing): one line per failure, format
   `<iso-ts> [<level>] source=<id> module=<name> kind=<kind> attempt=<1|2> exc=<type>: <msg>`.
2. **`_pipeline/cycles/cycle-NNN/agent-calls/`** (FR-024): a full
   AgentCallRecord with `error` set to the traceback, `retry_attempt`
   field set to 1 or 2. (Only applies for extractor failures, since
   they're the LLM-bearing surface. Validator + manifest failures
   skip this log.)

Both logs are CRASH-SAFE \u2014 written line-by-line with `flush()` so a
subsequent crash doesn't lose the record.

## Cycle-level invariant

> **A cycle MUST NEVER abort due to module-subsystem failure,
> regardless of how many sources or modules fail.**

Tested via `test_module_isolation.py::test_all_sources_fail_cycle_continues`:

- Configure a vault with 3 sources.
- Inject failures in all 3 extractors (controllable via fake_module.py).
- Assert: `cycle_runner.run_cycle_steps()` completes with exit 0.
- Assert: run-report contains 3 entries in "Per-source failures".
- Assert: cycle's other stages (scout, note_writer) still run on
  the empty signal set (no signals \u2192 scout produces zero topics \u2192
  empty cycle, but a CLEAN empty cycle).

## Distinction from drift detection (D8)

D8 (schema drift) IS fail-closed. D9 (module isolation) is fail-open.

These are different concerns:
- Schema drift is the USER's responsibility issue \u2014 they opted into
  `manually_edited: true`. Fail-closed forces the user to address it.
- Module failure is a SYSTEM resilience issue. Fail-open keeps the
  cycle productive when some sources are broken.

`--force-stale-schema` only overrides D8. Module isolation has no
override flag because it's the default behavior.

## CLI surface

No new CLI flags for module isolation (always-on). Existing
`--verbose` and the run-report do the surfacing.

## Test fixtures

`tests/source_bridge/test_module_isolation.py` covers:

- **`test_extractor_timeout_retried_once`** \u2014 extractor hangs 700s
  on first call, returns valid payload on second. Verify: 1 retry,
  final payload written, no failure in run-report.
- **`test_extractor_fails_twice_partial_salvaged`** \u2014 extractor crashes
  after writing 12/40 facts both times. Verify: partial payload
  written with `verdict: "error"`, `partial: true`; failure
  surfaced in run-report.
- **`test_validator_py_exception_retried`** \u2014 validator raises on
  first call, succeeds on second. Verify: 1 retry, normal validation
  outcome.
- **`test_validator_py_always_raises`** \u2014 validator raises both
  times. Verify: source marked failed; cycle continues.
- **`test_manifest_parse_error_excludes_module`** \u2014 manifest has
  invalid YAML. Verify: module not in trigger registry; other
  modules unaffected; "Module discovery issues" entry in run-report.
- **`test_all_sources_fail_cycle_continues`** \u2014 cycle-level
  invariant.
