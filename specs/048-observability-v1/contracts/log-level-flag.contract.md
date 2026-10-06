# Contract: `--log-level` CLI flag

**Authority**: Spec 048 FR-004, FR-005. Behavior is testable via `tests/observability/test_log_surfaces.py`.

## Surface

```
--log-level {debug,info,warning,error}
```

- **Scope**: Global flag. Applies to ALL subcommands of the `research-framework` CLI: `research`, `health`, `update`, `regenerate`, `onboard`, `install`, `scaffold`, `write`, and any future subcommand.
- **Argument parser**: Registered at the top-level `argparse.ArgumentParser`, BEFORE the subcommand dispatch (so subcommands inherit it without re-declaring).
- **Allowed values** (case-insensitive on input, normalized to lowercase internally): `debug`, `info`, `warning`, `error`.
- **Disallowed**: `critical`, `notset`, integers, mixed case unless normalized.

## Default selection algorithm (FR-005, TTY-aware)

```python
def _detect_default_level() -> int:
    """Return the logging level constant to use when --log-level is unset."""
    import logging
    import sys
    if sys.stdout.isatty():
        return logging.INFO
    return logging.WARNING
```

- The default is detected exactly **once** at CLI entry. Sub-shell redirection mid-process does not re-evaluate.

### Per-verb default (issue #241, 2026-09-06)

`resolve(value, *, verb_default=None)` consults the verb's own declared default
*before* the TTY test, and only when `--log-level` is absent. A subparser
declares one with `set_defaults(verb_default_log_level="info")`.

Today exactly one verb family declares it: `pipeline`. The TTY test is a good
proxy for "is a human watching" everywhere except the one place it matters
most — an autonomous pipeline runs from cron/launchd/systemd and is therefore
*never* on a TTY, so FR-005 silenced every phase summary, the `HUMAN TRIAGE
REQUIRED` prompt, the verify verdict and the "not yet implemented" collect
lines in exactly the mode the framework exists for.

The precedence is: explicit `--log-level` → `verb_default_log_level` →
`_detect_default_level()`. A `verb_default` is validated on the same path as a
flag value, so a typo raises `ValueError` rather than silently reverting.
- The detected default is itself logged at DEBUG level (`logger.debug("default log level: INFO (TTY detected)")`) so diagnostic runs can confirm what happened.
- No environment variable override (`NO_COLOR`, `TERM`, etc.) is honored. The flag is the override.

## Error mode

Invalid `--log-level` value (e.g. `--log-level INVALID`):

- `argparse` rejects with exit code **2** and the standard `argparse` error message naming the four allowed values.
- No `logging.basicConfig` call has been made yet at this point (the error happens before logger wiring).
- The error message is delivered to stderr (argparse default).

## Interaction with `basicConfig` (FR-001/002)

- The flag value (or detected default) is passed as `level=` to `logging.basicConfig(...)` exactly once at startup.
- If `logging.root.handlers` is non-empty at CLI entry (e.g. running under pytest), `basicConfig` is skipped entirely AND `--log-level` is silently ignored (parent process owns the configuration). A DEBUG log records "parent process configured root logger; --log-level ignored" for diagnostics.

## Test surface (FR-015 will assert this)

```python
def test_log_level_default_is_info_under_tty(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert _detect_default_level() == logging.INFO

def test_log_level_default_is_warning_when_piped(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _detect_default_level() == logging.WARNING

def test_log_level_flag_overrides_default(capsys):
    # Run a subcommand with --log-level debug; assert DEBUG records reach stderr.
    ...

def test_log_level_invalid_value_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--log-level", "INVALID", "research"])
    assert exc.value.code == 2
    assert "INVALID" in capsys.readouterr().err
```

## Out of scope

- Per-module log levels (`--log-level pipeline.scout=debug,bridge=error`) — v1.1+ consideration.
- `--quiet` / `-v`/`-vv` shorthand — argparse can synthesize from the flag if ever needed; for now, the explicit value wins.
- Coloring log records by level — future v2 consideration (would need `NO_COLOR` handling at that point).
