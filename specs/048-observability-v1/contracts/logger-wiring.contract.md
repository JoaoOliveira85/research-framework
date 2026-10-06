# Contract: Root logger wiring at CLI entry

**Authority**: Spec 048 FR-001, FR-002, FR-003. Behavior is testable via `tests/observability/test_log_surfaces.py`.

## Invariants

1. **`logging.basicConfig()` is called at most once per process.** Idempotent against re-entry; see FR-002.
2. **The configuration happens BEFORE any pipeline code runs.** Specifically: at the top of `research_framework.cli.__main__.main()`, after argparse parses `--log-level` but before any subcommand dispatch.
3. **Every module-level logger MUST be created via `logging.getLogger(__name__)`.** Never `logging.getLogger("research_framework.foo")` (typo risk; fragile against future renames). Never `logging.getLogger()` (root logger). Never module-level `logger = logging.Logger(...)` (skips the registry).
4. **Output stream is `sys.stderr`.** Not stdout (avoids polluting future JSON-output paths). The framework's structured stdout artifacts (run-report, final-report) write to stdout via `print()` and remain unaffected.
5. **Format string is locked**: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. No colorization, no extra fields, no JSON.
6. **No propagation hacks.** No `logger.propagate = False`, no custom handlers attached to individual loggers in framework code. (Tests MAY add handlers via `caplog`; that's pytest's contract.)

## Reference implementation

```python
# src/research_framework/cli/__main__.py
import logging
import sys
from . import _log_level


def _configure_root_logger(level: int) -> None:
    """Wire logging.basicConfig once per process.

    Idempotent against re-entry (FR-002): if any handler is already attached
    to the root logger (e.g. pytest's LogCaptureHandler), do nothing.
    """
    if logging.root.handlers:
        # Parent process owns the configuration. Do not double-configure.
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_top_level_parser()  # registers --log-level
    args, remainder = parser.parse_known_args(argv)
    level = _log_level.resolve(args.log_level)  # TTY-aware default
    _configure_root_logger(level)
    logger = logging.getLogger(__name__)
    logger.debug("CLI entry; log level resolved to %s", logging.getLevelName(level))
    return _dispatch_subcommand(args, remainder)
```

## Module-level logger pattern (FR-003)

Every framework module that emits logs MUST do this at module top, NOT inside a function:

```python
# src/research_framework/pipeline/cycle_runner.py
import logging
logger = logging.getLogger(__name__)

def run_cycle_steps(...):
    logger.info("cycle %d / %d starting", cycle_number, total_cycles)
    ...
```

The resulting logger name will be `research_framework.pipeline.cycle_runner`, matching the dotted Python path.

## Test surface (FR-015 enforces)

```python
def test_basicconfig_called_once_per_process(capsys):
    # Invoking main() twice in the same Python process MUST NOT add a second handler.
    main(["--log-level", "info", "regenerate", "--help"])
    handlers_after_first = list(logging.root.handlers)
    main(["--log-level", "debug", "regenerate", "--help"])
    handlers_after_second = list(logging.root.handlers)
    assert handlers_after_first == handlers_after_second

def test_logger_name_matches_module_dotted_path():
    # Sanity: every module in src/research_framework/ that uses `logger`
    # uses `getLogger(__name__)`.
    forbidden_patterns = (
        r"logging\.getLogger\(\)",            # bare root
        r'logging\.getLogger\("[^_]',         # literal string (not __name__)
        r"logger = logging\.Logger\(",        # bypass registry
    )
    # AST or grep across src/research_framework/**/*.py; assert no matches.

def test_root_logger_skipped_when_already_configured():
    # Simulate pytest having configured the root logger first.
    handler = logging.StreamHandler()
    logging.root.addHandler(handler)
    try:
        _configure_root_logger(logging.DEBUG)
        # Our basicConfig should be a no-op — handler count unchanged.
        assert handler in logging.root.handlers
        assert len(logging.root.handlers) == 1
    finally:
        logging.root.removeHandler(handler)

def test_logger_records_format_pinned(caplog):
    caplog.set_level(logging.INFO)
    logger = logging.getLogger("research_framework.test_module")
    logger.info("hello")
    record = caplog.records[-1]
    assert record.name == "research_framework.test_module"
    assert record.levelname == "INFO"
    assert record.message == "hello"
```

## Forbidden patterns

| Pattern | Why forbidden | Alternative |
|---|---|---|
| `logging.basicConfig(force=True)` | Breaks pytest's `caplog` fixture; double-configures handlers under script wrappers | Use the FR-002 idempotent guard |
| `logger.propagate = False` | Hides records from parent processes / pytest capture | Let propagation default to True |
| `print("[DEBUG] ...")` in new framework code | Bypasses level filtering and TTY-aware default | `logger.debug(...)` |
| `logging.getLogger().info(...)` (root logger) | Loses the module-path context | `logger = logging.getLogger(__name__); logger.info(...)` |
| `logging.getLogger("research_framework.pipeline.scout")` (literal string) | Drifts if module is renamed | `logging.getLogger(__name__)` |
| `import structlog` (or any logging-related new dep) | Principle V violation | Stdlib `logging` only |

## Interaction with FR-012 (hot-path `print()` migration)

The migration touches ~80 `print()` call sites in:

- `src/research_framework/pipeline/cycle_runner.py`
- `src/research_framework/pipeline/orchestrator.py`
- `src/research_framework/pipeline/runner.py`
- `src/research_framework/pipeline/steps/scout.py`
- `src/research_framework/pipeline/steps/research.py`
- `src/research_framework/pipeline/steps/postprocess.py`
- `src/research_framework/pipeline/source_bridge/orchestrator.py`

Each file MUST grow a module-level `logger = logging.getLogger(__name__)` declaration at the top during the migration. The replacement rule:

- `print("informational message")` → `logger.info("informational message")`
- `print("⚠ actionable warning")` → `logger.warning("actionable warning")` (strip the emoji prefix — log levels carry the semantic now)
- `print(f"value = {x}")` → `logger.info("value = %s", x)` (use `%s` lazy formatting, NOT f-strings — saves work at WARNING+ level)

Non-hot-path `print()` calls stay as-is in MVP per FR-014 deferral. The regression test (FR-015) compares the hot-path count against a snapshot baseline.

## Out of scope

- Per-logger level configuration (`logger = logging.getLogger("research_framework.pipeline.scout"); logger.setLevel(logging.DEBUG)`) — possible but not used in MVP code. Operators control verbosity via the global flag.
- Log rotation (`RotatingFileHandler` for the stderr stream). Out of scope: stderr is the operator's terminal, not a persisted log file.
- Sentry / error-tracking integration. Out of scope per spec (external observability is v2).
