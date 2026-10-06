# Contract — opencode adapter (`scripts/agent_call.py`)

## Registration

```python
_RUNTIME_ADAPTERS["opencode"] = _opencode_cmd          # CLI adapter
_LLM_AGENT_NAMES |= {"opencode"}                        # it is an LLM agent
# opencode is NOT added to _HTTP_RUNTIMES, _FLAT_RATE_AGENTS, or _STREAMING_AGENTS
# (its cost class is resolved PER CALL — see cost contract below).
```

`valid_runtimes()` (benchmark) MUST then include `"opencode"` with no other change.

## Command builder

```
_opencode_cmd(executor: dict, vault_dir: Path | None = None) -> list[str]
```

MUST produce:

```
[OPENCODE_BIN, "run", "--format", "json", "--model", <model>]
  + (["--variant", <variant>]   if executor.get("variant"))
  + (["--agent", <agent>]       if executor.get("agent"))
  + (["--dir", str(vault_dir)]  if vault_dir is not None and not _has_dir_flag(args))
  + args
```

- `OPENCODE_BIN` from env `OPENCODE_BIN` else `"opencode"`.
- Prompt is fed on stdin (not argv) — consistent with the other adapters.
- `_has_dir_flag(args)` true for `--dir` / `--dir=…` so an operator override wins (no double flag).
- `_build_command` MUST gain an `opencode` branch (like `codex`/`cursor-agent`)
  so `vault_dir` reaches `_opencode_cmd`.

## MUST / MUST NOT

- MUST NOT emit `--dangerously-skip-permissions` as the *containment* mechanism;
  containment is `--dir`. (`--dangerously-skip-permissions`, if used at all, is an
  approval-posture choice that lives in `args` from the settings profile.)
- MUST NOT alter the command produced for `claude` / `codex` / `cursor-agent`
  (FR-014) — byte-identical adapters; assert in a regression test.
- MUST raise the existing unknown-runtime `ValueError` listing `opencode` among
  supported runtimes (it now is).

## Tests (tier-2 unit, hermetic — no real opencode)

- `_opencode_cmd` shape: model, `--format json`, `--dir` injection, operator `--dir`
  override, optional `--variant`/`--agent`, env `OPENCODE_BIN`.
- `_build_command("opencode", …)` routes through `_opencode_cmd` with `vault_dir`.
- unknown-runtime error message includes `opencode`.
- regression: claude/codex/cursor command builders unchanged.
