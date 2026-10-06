# Research: Observability v1 MVP

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Date**: 2026-05-29

Most decisions were locked in `/speckit.specify` (TTY-aware default, per-cycle `bridge.log`, hot-path-only `print()` migration) and `/speckit.clarify` (line-buffered stderr capture). This document records the four remaining "best practice" reviews so the implementation doesn't drift toward avoidable patterns.

---

## R1 — TTY detection: `sys.stdout.isatty()` only

**Decision**: Use `sys.stdout.isatty()` as the sole TTY signal. No `os.isatty(0)` (stdin), no `os.isatty(1)`, no `TERM` / `NO_COLOR` environment variable inspection, no `--force-tty` flag.

**Rationale**:
- Matches the conventions used by `pytest`, `ruff`, `pip`, `rich` — operators expect the same answer the tools they already use give.
- One source of truth means the FR-005 acceptance test can pin the value directly without proxying.
- Pseudo-TTY edge cases (containers, `tmux`, `script(1)`) are an explicit acceptable false-positive — the user can override via `--log-level` if they want a different default.

**Alternatives considered**:
- *Test all three FDs (0/1/2) and OR them together*: rejected. If stderr is piped but stdout is a TTY, the user is most likely running interactively, and `--log-level info` is the right call.
- *Honor `NO_COLOR`*: rejected for v1.0. We're not coloring output yet. If/when colorized log records ship (out of scope per spec), revisit.
- *`--force-tty` override flag*: rejected as YAGNI. `--log-level info` is a strictly better escape hatch (more specific intent).

**Touch point**: `src/research_framework/cli/_log_level.py::_detect_default_level()`.

---

## R2 — Line-buffered stderr capture: `Popen(bufsize=1, universal_newlines=True)` + daemon reader thread

**Decision**: Per-extractor subprocess invocation creates `Popen` with `bufsize=1, universal_newlines=True` and spawns a `threading.Thread(target=_drain, daemon=True)` that reads `proc.stderr` line-by-line via the standard for-loop iterator (`for line in proc.stderr:`). Each line is forwarded to the shared `BridgeLogWriter` via a `threading.Lock`.

**Rationale** (spec Q1 / FR-007):
- The Python `subprocess` module's `bufsize=1` is documented to mean "line buffered" only when `universal_newlines=True` (i.e. text mode). The pair is the stdlib-blessed way.
- `daemon=True` ensures the reader thread terminates with the parent process if the orchestrator exits hard (Ctrl-C, wall-clock kill). The reader does not need to be joined — the framework only needs the partial content captured up to the SIGTERM.
- A separate thread per extractor is OK because Wave-2 modules currently invoke extractors sequentially. Even if N parallel extractors land later, N reader threads is a fine cost (~1 KB stack each, blocking on a pipe so no CPU spin).
- The `Lock` around bridge-log writes serializes interleaved output. Without it, two extractors writing simultaneously could corrupt a line. With it, writes are atomic at the line granularity.

**Alternatives considered**:
- *Spec Q1 Option C — `select()` event loop in the orchestrator*: rejected per the user's /clarify choice. Theoretical efficiency gain doesn't matter for sequential extractors; adds complexity.
- *`asyncio` subprocess reader*: rejected. The framework's runtime is synchronous Python; introducing `asyncio` only for this surface is disproportionate.
- *Polling `proc.stderr.readline()` in the orchestrator main thread*: rejected. Would block the orchestrator on a slow extractor — defeats the live-watch purpose.

**Touch points**:
- `src/research_framework/observability/extractor_capture.py::start_capture(proc, module, source_id, writer)`.
- `src/research_framework/pipeline/source_bridge/extractor.py` — wire `start_capture()` around the existing `Popen` invocation.

---

## R3 — Logger config idempotency: detect pre-configured root

**Decision**: At CLI entry, `logging.basicConfig()` is called inside a guard:

```python
import logging
def _configure_root_logger(level: int) -> None:
    if logging.root.handlers:
        # Parent process (e.g. pytest) already wired the root logger.
        # Do not double-configure — that produces duplicate output and
        # surprises the parent's capture mechanism.
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
```

**Rationale** (FR-002):
- `pytest` installs a `LogCaptureHandler` on the root logger by default. If we then `basicConfig()` on top, we get duplicated output AND pytest's `caplog` fixture stops capturing reliably.
- The CPython `logging.basicConfig` function itself is a no-op when handlers are already configured — but only if `force=False` (the default). We rely on the documented behavior, AND we make it explicit so future maintainers don't add `force=True` "for safety".
- This makes the framework safely embeddable: any tool that imports `research_framework.cli` programmatically inherits the parent's logger.

**Alternatives considered**:
- *Use `logging.basicConfig(force=True)`*: rejected. Would break pytest's `caplog` fixture.
- *Install our own handler manually instead of `basicConfig`*: rejected. `basicConfig` is the stdlib-blessed entry point and matches what 99% of Python tools do; pattern-match wins.

**Touch point**: `src/research_framework/cli/__main__.py` (top of `main()`).

---

## R4 — `bridge.log` write contention: per-cycle file + threading.Lock

**Decision**: One `bridge.log` file per cycle, opened in append-text mode at cycle start, closed at cycle end. Writes are serialized via a single `threading.Lock` shared across all reader threads for that cycle.

**Rationale** (FR-006):
- Wave-2 extractors are sequential today. Contention is theoretical.
- The lock is essentially free when uncontended (~50 ns acquire/release on Linux/macOS).
- Per-extractor-process log files were considered (and explicitly rejected in spec Out of Scope) — splitting would add a `bridge-<module>-<pid>.log` filename convention that complicates `tail -f`-the-current-cycle.
- The file is the *only* output for the reader threads; no in-memory buffering layer, so a crash mid-write loses at most one partial line.

**Alternatives considered**:
- *Use Python's `logging.handlers.QueueHandler` for cross-thread coordination*: rejected. Adds an additional layer of indirection (logger record → queue → flush thread → file) that obscures what's happening; a `Lock` around the file write is far more direct.
- *Open the file fresh for each extractor invocation (append mode), close on exit*: rejected. Re-opening on every extractor adds syscall noise and means a hang between extractors could leave the file in an inconsistent state.

**Touch points**:
- `src/research_framework/observability/bridge_log.py::BridgeLogWriter` — the file + lock + framing logic.
- `src/research_framework/pipeline/cycle_runner.py` — open at cycle start, close at cycle end, pass writer to the source-bridge orchestrator.

---

## Cross-cutting: rejected for v1.0

These came up during research; each is documented so it doesn't get re-litigated:

- **`structlog`**: rejected — Principle V (no new runtime deps).
- **OpenTelemetry exporters / Datadog SDK / Prometheus client**: rejected — explicit spec Out of Scope.
- **Per-module log file split (`bridge-youtube.log`, etc.)**: rejected — explicit spec Out of Scope.
- **`asyncio` subprocess driver**: rejected — disproportionate to the use case.
- **Full migration of all ~125 pipeline `print()` calls in v1.0**: rejected per /clarify; hot-path-only ships value faster.

## References

- Spec: [spec.md](./spec.md) (FRs 001-008, 012, 015/016 are the MVP scope)
- Plan: [plan.md](./plan.md)
- ADR-0007: smoke-gate mandatory (no `--skip-smoke`)
- ADR-0010: foreman verification pattern (TDD discipline)
- Constitution: Principle V (no new deps), Principle III (TDD non-negotiable)
- Sibling doc (separate deliverable): `docs/observability-strategy.md` — written during /implement
