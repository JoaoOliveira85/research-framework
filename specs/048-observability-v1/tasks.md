# Tasks: Observability v1 — MVP cut

**Input**: Design documents from `/specs/048-observability-v1/`
**Prerequisites**: plan.md (MVP-scoped), spec.md (CLARIFIED 2026-05-29), research.md, data-model.md, contracts/{log-level-flag,bridge-log-format,logger-wiring}.contract.md, quickstart.md
**Branch**: `048-observability-v1`

**Tests**: Required (Constitution Principle III — TDD non-negotiable; ADR-0010 foreman verification pattern). Every implementation task carries a `### Testing Requirements` block; tests MUST land in the same-or-earlier commit as the implementation per the foreman TDD-discipline flag.

**Organization**: Phases follow user-story priority per spec.md MVP cut. US1 (live watch — P1) and US2 (debug stuck extractor — P1) share infrastructure (`bridge.log` writer + reader thread); US1 ships the live-buffered guarantee, US2 extends with the KILLED footer. US3 (verbosity dial — P2) layers on Foundational `--log-level` plus a hot-path `print()` sweep. US5 (regression guard — P2) consolidates surface-discipline tests. US4 is deferred to v1.1 (no tasks here).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: US1, US2, US3, US5 map to spec.md user stories. Setup + Foundational + Polish tasks have no story label.
- All paths are repo-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the empty package layout and test-fixture scaffolding so subsequent tasks have somewhere to land.

- [ ] T001 Create `src/research_framework/observability/__init__.py` (empty file — exports added by later tasks)
- [ ] T002 [P] Create `tests/observability/__init__.py` (empty file) and `tests/observability/_fixtures/__init__.py` (empty file)
- [ ] T003 [P] Create the sentinel extractor fixture at `tests/observability/_fixtures/sentinel_extractor.py` — a self-contained Python script that emulates a spec-020 extractor: reads JSON request from stdin, writes deterministic `[STAGE-N]` lines to stderr (one per N=1..3 with a `time.sleep(1.0)` between them), writes a minimal valid `SignalPayload` JSON to stdout, exits with the requested exit code. Used by the line-buffered probe (FR-007 acceptance).

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_sentinel_extractor_writes_three_stderr_lines_with_pauses`
    - Behavior: Run `sentinel_extractor.py` as subprocess with `exit_code=0`; assert stderr contains exactly `[STAGE-1]`, `[STAGE-2]`, `[STAGE-3]`; assert total runtime ≥ 2.0s (two `time.sleep(1.0)` pauses); assert stdout parses as JSON with `verdict == "ok"`.
    - Tier: 2

  **TDD discipline**: not required — the fixture and its test ARE the same artifact (test infrastructure, not production code under `src/`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire the root logger (FR-001/002/003), add the `--log-level` flag with TTY-aware default (FR-004/005). Every user story depends on these landing first — no story work begins until Phase 2 is GREEN.

**⚠️ CRITICAL**: Do not start Phase 3+ until T010 is green.

- [ ] T004 Implement `src/research_framework/cli/_log_level.py` per `contracts/log-level-flag.contract.md` § Default selection algorithm. Exports `add_log_level_arg(parser)` (registers the flag on a parser) and `resolve(arg_value: str | None) -> int` (returns the `logging` level constant, using TTY-aware default when arg is None). No side effects (no `basicConfig` here — that's T005).

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_log_level_default_is_info_under_tty`
    - Behavior: `monkeypatch.setattr("sys.stdout.isatty", lambda: True)`; assert `_log_level.resolve(None) == logging.INFO`.
    - Tier: 2
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_log_level_default_is_warning_when_piped`
    - Behavior: `monkeypatch.setattr("sys.stdout.isatty", lambda: False)`; assert `_log_level.resolve(None) == logging.WARNING`.
    - Tier: 2
  - **Test 3**: `tests/observability/test_log_surfaces.py::test_log_level_resolve_with_explicit_value`
    - Behavior: Call `_log_level.resolve("debug")` → `logging.DEBUG`; `_log_level.resolve("WARNING")` (case-insensitive) → `logging.WARNING`; `_log_level.resolve("INVALID")` → raise `ValueError`.
    - Tier: 2

  **TDD discipline**: required — tests above land in the same commit as `_log_level.py`.

- [ ] T005 Modify `src/research_framework/cli/__main__.py`: register `--log-level` on the top-level argparse parser via `_log_level.add_log_level_arg(parser)`; add `_configure_root_logger(level: int) -> None` private function per `contracts/logger-wiring.contract.md` § Reference implementation (idempotent guard against `logging.root.handlers`); call it once at the top of `main()` after `parse_known_args` and BEFORE subcommand dispatch.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_basicconfig_called_once_per_process`
    - Behavior: Invoke `main(["--log-level", "info", "regenerate", "--help"])` twice in same process (using `try: ... except SystemExit: pass` around each — `--help` exits 0); capture `len(logging.root.handlers)` after each call; assert handler count is identical (no double-config).
    - Tier: 2
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_root_logger_skipped_when_already_configured`
    - Behavior: Add a `logging.StreamHandler()` to `logging.root.handlers` before calling `_configure_root_logger(logging.DEBUG)`; assert our handler list is unchanged (the pre-existing handler stays alone; no new basicConfig handler added).
    - Tier: 2
  - **Test 3**: `tests/observability/test_log_surfaces.py::test_log_level_flag_invalid_value_exits_2`
    - Behavior: `with pytest.raises(SystemExit) as exc: main(["--log-level", "INVALID", "regenerate", "--help"])`; assert `exc.value.code == 2`; assert `"INVALID"` appears in `capsys.readouterr().err`.
    - Tier: 2
  - **Test 4**: `tests/observability/test_log_surfaces.py::test_log_record_format_pinned`
    - Behavior: After `_configure_root_logger(logging.INFO)`, create a `logging.getLogger("research_framework.test_module")` and emit `logger.info("hello")`; capture stderr via `capsys`; assert the emitted line matches the locked regex `r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[INFO\] research_framework\.test_module: hello$"`.
    - Tier: 2

  **TDD discipline**: required — tests above land in the same commit as the `__main__.py` modification.

- [ ] T006 [P] Add `tests/observability/conftest.py` with shared fixtures: `reset_root_logger` (autouse function-scoped — saves/restores `logging.root.handlers` around each test so T004/T005 tests don't pollute each other), `sentinel_extractor_path` (returns `Path` to `_fixtures/sentinel_extractor.py`), `tmp_vault_pipeline_dir` (creates `<tmp>/_pipeline/cycles/cycle-001/` and yields the path).

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_reset_root_logger_fixture_restores_state`
    - Behavior: Inside a test, add a handler to `logging.root`; assert teardown restores the pre-test handler count (verifies the autouse fixture actually works).
    - Tier: 2

  **TDD discipline**: required — fixture and test land in same commit.

- [ ] T007 Add a lint guard test: `tests/observability/test_log_surfaces.py::test_logger_name_matches_module_dotted_path`. Walks every `.py` file under `src/research_framework/` via `ast.parse`; asserts every `logging.getLogger(...)` call uses either `__name__` or a `getLogger` with no arguments (root logger — banned by FR-003); also flags literal-string `getLogger("some.literal")` patterns. Fails the test if any violation found. **MVP scope**: at this point only `cli/_log_level.py` and `cli/__main__.py` use the pattern; T013/T021/T024 add more. The test reads the source, so it auto-expands as more files use loggers. **This is a pure test task — no production code; foreman verifier should treat as test-only and skip Testing Requirements check.**

- [ ] T008 Verify Phase 2 GREEN: run `pytest tests/observability/ -v` and assert all T003-T007 tests pass. No new code in this task — purely a checkpoint to confirm Foundational is solid.

**Checkpoint**: Logger wired; `--log-level` flag operational; module-logger discipline enforced. User-story phases can begin.

---

## Phase 3: User Story 1 — Watch an unattended cycle live (Priority: P1) 🎯 MVP

**Goal**: An operator can `tail -f <vault>/_pipeline/cycles/cycle-NNN/bridge.log` during an active cycle and see extractor stderr in real time (≤2s latency).

**Independent Test**: With the sentinel extractor running for ~3s, a background thread polls `bridge.log` during the run. Assertion: at least the first stderr line (`[STAGE-1]`) is readable in `bridge.log` BEFORE the subprocess exits. This proves the line-buffered guarantee (FR-007).

### Tests for User Story 1

- [ ] T009 [P] [US1] Add `tests/observability/test_log_surfaces.py::test_bridge_log_header_footer_framing`. Build a `BridgeLogWriter` instance against a `tmp_path/bridge.log`; call `writer.start_extractor(module="youtube", source="VID_X", pid=12345)` → asserts header line matches `contracts/bridge-log-format.contract.md` § Header regex. Write 3 body lines via `writer.write_body("[youtube:12345] line N")` for N=1..3. Call `writer.end_extractor(exit_code=0, duration=4.328, payload_status="ok")` → asserts footer matches success-path regex. Close writer. Read file; assert line count = 1+3+1 = 5; assert all lines parse against their respective regexes.

- [ ] T010 [P] [US1] Add `tests/observability/test_log_surfaces.py::test_bridge_log_is_line_buffered`. Open a `BridgeLogWriter` against `tmp_path/bridge.log`; spawn the sentinel extractor as subprocess via the SAME mechanism `extractor_capture.start_capture()` will use; in the main thread, poll `bridge.log` every 100ms during the 2s sentinel runtime. Assert: by the time the sentinel has exited (~2-3s elapsed), at least the `[STAGE-1]` body line is present in `bridge.log`, AND the polling loop observed the file growing (i.e. content present BEFORE `proc.wait()` returned).

  **Note**: This is the FR-007 critical guarantee. If it fails, the whole spec value-prop fails. Test name is the regression-discipline anchor.

### Implementation for User Story 1

- [ ] T011 [US1] Implement `src/research_framework/observability/bridge_log.py` containing the `BridgeLogWriter` class per `contracts/bridge-log-format.contract.md`. API: `__init__(path: Path)` opens file in append-text-UTF-8 mode and creates `threading.Lock()`; `start_extractor(module, source, pid)` writes header line; `write_body(line: str)` acquires lock and appends `line + "\n"`; `end_extractor(exit_code, duration_s, payload_status)` writes success footer; `end_extractor_killed(reason, duration_s)` writes KILLED footer (delegated to in T015); `close()` is idempotent. Header/footer formats must match the regex grammar in the contract verbatim.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_bridge_log_header_footer_framing` (the T009 test — must pass after this task lands).
    - Tier: 2
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_bridge_log_writer_close_is_idempotent`
    - Behavior: Call `writer.close()` twice; assert no exception, file size unchanged on second call.
    - Tier: 2
  - **Test 3**: `tests/observability/test_log_surfaces.py::test_bridge_log_writer_acquires_lock_during_write`
    - Behavior: Mock `threading.Lock`; assert `acquire()` + `release()` is called exactly once per `write_body` invocation.
    - Tier: 2

  **TDD discipline**: required — tests above land in the same commit as `bridge_log.py`.

- [ ] T012 [US1] Implement `src/research_framework/observability/extractor_capture.py` with the `start_capture(proc, module, source, writer) -> threading.Thread` function. Spawns a `daemon=True` thread that iterates `proc.stderr` line-by-line; for each line, calls `writer.write_body(f"[{module}:{proc.pid}] {line.rstrip()}")`. Returns the thread handle (caller must `.join()` after `proc.wait()`).

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_bridge_log_is_line_buffered` (the T010 test — must pass after this task lands).
    - Tier: 2
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_extractor_capture_thread_is_daemon`
    - Behavior: Mock a `subprocess.Popen`-like object; assert the returned thread has `daemon=True`.
    - Tier: 2
  - **Test 3**: `tests/observability/test_log_surfaces.py::test_extractor_capture_prefixes_lines_with_module_and_pid`
    - Behavior: Mock a Popen-like object whose `stderr` yields `["line A\n", "line B\n"]`; collect what `writer.write_body()` was called with; assert calls match `[f"[youtube:{pid}] line A", f"[youtube:{pid}] line B"]`.
    - Tier: 2

  **TDD discipline**: required — tests above land in the same commit as `extractor_capture.py`.

- [ ] T013 [US1] Modify `src/research_framework/pipeline/cycle_runner.py`: open a `BridgeLogWriter` at cycle start (path = `<vault>/_pipeline/cycles/cycle-{NNN:03d}/bridge.log`), close it in a `try/finally` at cycle exit. Wire the writer instance into the source-bridge dispatch path so extractor invocations can call `start_capture(proc, module, source, writer)`. Add `logger = logging.getLogger(__name__)` at module top per FR-003.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_cycle_runner_creates_bridge_log_at_cycle_start`
    - Behavior: Use the `tmp_vault_pipeline_dir` fixture; invoke a minimal `run_cycle_steps()` path with a fake-agent stub (re-use `tests/_helpers/fake_agent.py`); assert `_pipeline/cycles/cycle-001/bridge.log` is created BEFORE any extractor is dispatched.
    - Tier: 3
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_cycle_runner_closes_bridge_log_on_exception`
    - Behavior: Inject an exception mid-cycle; assert the `bridge.log` file handle is closed (test via `state.bridge_log_writer.closed == True` introspection or by attempting a second `close()` that should be a no-op).
    - Tier: 3

  **TDD discipline**: required — tests above land in the same commit as the `cycle_runner.py` modification.

- [ ] T014 [US1] Modify `src/research_framework/pipeline/source_bridge/extractor.py` (or `orchestrator.py` if the dispatch lives there — verify via Glob): around the `subprocess.Popen(...)` call that invokes the module extractor, replace existing `stderr=subprocess.PIPE` (likely) with `stderr=subprocess.PIPE, bufsize=1, universal_newlines=True`; immediately after `Popen()`, call `start_capture(proc, module_name, source_id, cycle_state.bridge_log_writer)` and stash the thread; after `proc.wait()`, call `thread.join(timeout=5.0)`; then call `writer.end_extractor(exit_code, duration, verdict)`.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_extractor_dispatch_emits_full_framing_to_bridge_log`
    - Behavior: End-to-end via the sentinel extractor: dispatch a single extractor call through the source-bridge orchestrator (use existing `tests/source_bridge/` helpers if available; otherwise minimal harness). After dispatch returns, read `bridge.log` and assert: exactly one header, three body lines (`[STAGE-1]`, `[STAGE-2]`, `[STAGE-3]`), one success footer. All five lines match their regex grammars.
    - Tier: 3

  **TDD discipline**: required — test above lands in the same commit as the `extractor.py` modification.

**Checkpoint**: US1 fully shipped. An operator can `tail -f bridge.log` and watch extractor stderr in real time during a cycle.

---

## Phase 4: User Story 2 — Debug a stuck extractor post-mortem (Priority: P1)

**Goal**: A killed extractor's partial stderr is preserved in `bridge.log`, framed by a KILLED footer naming the reason. An operator can read the post-mortem and identify root cause in <2 minutes.

**Independent Test**: Spawn the sentinel extractor with `exit_code=0` but kill it via SIGTERM from the test after 1.5s (mid-pause). Assert: `bridge.log` contains the header, at least the `[STAGE-1]` body line (written before kill), and a footer line matching `=== KILLED BY FRAMEWORK \(<reason>\) after \d+\.\d{3}s ===`.

### Tests for User Story 2

- [ ] T015 [P] [US2] Add `tests/observability/test_log_surfaces.py::test_bridge_log_killed_footer_preserves_partial_stderr`. Use the sentinel extractor; in the test, after spawning, set up a `threading.Timer(1.5, lambda: writer.end_extractor_killed("manual interrupt", elapsed))` that calls the kill-path; assert the resulting `bridge.log` has the header line, the `[STAGE-1]` body line, and the KILLED footer matching the contract regex. Stage 2 + 3 lines MAY OR MAY NOT be present (depends on race timing — the assertion accepts both).

- [ ] T016 [P] [US2] Add `tests/observability/test_log_surfaces.py::test_bridge_log_killed_footer_regex_parses`. Pure unit test: feed example KILLED-footer strings (one per allowed reason value: `wall-clock cap`, `dollar cap`, `manual interrupt`, `parent exit`) through the contract's regex from `contracts/bridge-log-format.contract.md`; assert all four parse cleanly; assert an invalid reason (`whatever`) does NOT match.

### Implementation for User Story 2

- [ ] T017 [US2] Extend `src/research_framework/observability/bridge_log.py::BridgeLogWriter` with `end_extractor_killed(reason: str, duration_s: float) -> None`. Validate `reason` against the enum from the contract (`wall-clock cap`, `dollar cap`, `manual interrupt`, `parent exit`); raise `ValueError` on any other value. Write footer line matching contract regex.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_bridge_log_killed_footer_preserves_partial_stderr` (the T015 test — must pass).
    - Tier: 2
  - **Test 2**: `tests/observability/test_log_surfaces.py::test_bridge_log_killed_footer_regex_parses` (the T016 test — must pass).
    - Tier: 2
  - **Test 3**: `tests/observability/test_log_surfaces.py::test_bridge_log_killed_footer_rejects_unknown_reason`
    - Behavior: Call `writer.end_extractor_killed("bogus reason", 1.0)`; assert `ValueError` raised; assert `bridge.log` unchanged (no footer written before the validation).
    - Tier: 2

  **TDD discipline**: required — tests above land in the same commit as the `end_extractor_killed` addition.

- [ ] T018 [US2] Wire the KILLED-path into the source-bridge orchestrator. In `src/research_framework/pipeline/source_bridge/orchestrator.py` (or wherever the wall-clock cap / kill detection lives — verify with Grep on `wall-clock` or `terminate`): when the orchestrator decides to kill an extractor (any of the four allowed reasons), drain remaining stderr via `thread.join(timeout=2.0)`, then call `writer.end_extractor_killed(reason, elapsed)`. Make sure the reader thread is given a chance to flush before the footer is written (FR-008).

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_orchestrator_writes_killed_footer_on_wall_clock_cap`
    - Behavior: Configure a fixture with a 1.0s wall-clock cap; dispatch the sentinel extractor (which sleeps 2s); after dispatch returns (with extractor killed), assert `bridge.log` contains a footer `=== KILLED BY FRAMEWORK (wall-clock cap) after 1.\d{3}s ===`.
    - Tier: 3

  **TDD discipline**: required — test above lands in the same commit as the orchestrator modification.

**Checkpoint**: US2 fully shipped. A killed extractor's post-mortem is readable from `bridge.log`.

---

## Phase 5: User Story 3 — Dial verbosity without code changes (Priority: P2)

**Goal**: An operator passes `--log-level debug` and sees ≥10x more log lines than at `--log-level warning`. The TTY-aware default (already in Phase 2) means interactive runs default to INFO; piped/CI runs default to WARNING.

**Independent Test**: Run a fixture cycle (or even just the `regenerate --help` path) twice: once with `--log-level debug`, once with `--log-level warning`. Count lines on captured stderr. Assert ratio ≥ 10:1 (per SC-004).

### Tests for User Story 3

- [ ] T019 [P] [US3] Add `tests/observability/test_log_surfaces.py::test_log_level_debug_flag_increases_record_count`. Configure a `caplog` fixture set to DEBUG; emit `logger.debug("d")`, `logger.info("i")`, `logger.warning("w")`, `logger.error("e")` from a test module's logger; assert all four reach `caplog.records`. Then re-run with caplog set to WARNING; assert only "w" and "e" reach it. (This is more about the level filtering than the CLI flag — combined with T005's test_log_level_flag_invalid_value_exits_2, the contract is covered.)

- [ ] T020 [P] [US3] Add `tests/observability/test_log_surfaces.py::test_log_level_dial_sc004_ratio`. SC-004 measure: invoke the CLI twice (`--log-level debug` vs `--log-level warning`) on a deterministic minimal path (the `regenerate --help` exit gives ~3 vs 0 lines; insufficient). Instead, programmatically: under `caplog.set_level(logging.DEBUG)`, simulate a sentinel "fake cycle" that emits 50 debug/info/warning records via a helper, capture record count; repeat under `caplog.set_level(logging.WARNING)`, capture count; assert `debug_count >= 10 * warning_count`.

### Implementation for User Story 3

- [ ] T021 [P] [US3] Migrate hot-path `print()` → `logger.info()` (or `.warning()` where actionable) in `src/research_framework/pipeline/cycle_runner.py`. Add module-level `logger = logging.getLogger(__name__)` at top. Use lazy `%s` formatting for INFO+ records (not f-strings) per `contracts/logger-wiring.contract.md`. Per `rg "^\s*print\("` count on 2026-05-29, this file has 17 prints — verify post-migration count is zero. **Also adds the parametrized test fixture** (the 7-file list) used by T022-T027.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized over the 7 hot-path files from FR-012. For each file, reads source, counts `print(` occurrences via AST (treating triple-quoted string literals containing "print(" as non-counts), asserts == 0. After this task lands, `cycle_runner.py` passes; the test is then re-used by T022-T027 to verify each subsequent migration.
    - Tier: 2

  **TDD discipline**: required — test above lands in same commit as migration.

- [ ] T022 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/orchestrator.py`. Add module-level `logger = logging.getLogger(__name__)`. ~30 prints to migrate per rg count. The single parametrized test `test_no_net_new_print_in_hot_path_files` from T021 covers all 7 files; once added to the test fixture's parametrize list, this file is checked automatically.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test from T021 runs against `orchestrator.py` — assert `print(` AST occurrence count == 0.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T023 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/runner.py`. ~25 prints. Add module-level logger.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test runs against `runner.py` — assert zero `print(` AST occurrences.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T024 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/steps/scout.py`. ~24 prints. Add module-level logger.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test runs against `steps/scout.py` — assert zero `print(` AST occurrences.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T025 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/steps/research.py`. ~6 prints. Add module-level logger.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test runs against `steps/research.py` — assert zero `print(` AST occurrences.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T026 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/steps/postprocess.py`. ~8 prints. Add module-level logger.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test runs against `steps/postprocess.py` — assert zero `print(` AST occurrences.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T027 [P] [US3] Migrate hot-path `print()` → `logger.info()` in `src/research_framework/pipeline/source_bridge/orchestrator.py`. ~1 print. Add module-level logger.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
    - Behavior: Parametrized test runs against `source_bridge/orchestrator.py` — assert zero `print(` AST occurrences.
    - Tier: 2

  **TDD discipline**: required.

**Checkpoint**: US3 fully shipped. `--log-level` dial works; hot-path `print()` calls are gone. Non-hot-path prints (~45) deliberately stay un-migrated per spec FR-014 v1.1 deferral.

---

## Phase 6: User Story 5 — Regression guard against silent log drops (Priority: P2)

**Goal**: A future refactor that silently breaks logging (e.g. accidental `logging.disable()`, a broken `bridge.log` writer) fails the regression suite in pre-commit, not in production.

**Independent Test**: Patch out `_configure_root_logger` to be a no-op; run `tests/observability/test_log_surfaces.py`; assert a specific test (`test_basicconfig_called_once_per_process` or `test_log_record_format_pinned`) fails with a message naming the lost surface.

### Tests for User Story 5

- [ ] T028 [US5] Add `tests/observability/test_log_surfaces.py::test_smoke_gate_includes_observability_surfaces`. Verifies that the observability tests are in the smoke-gate set per ADR-0007 + FR-016. Implementation: read `./build.sh`; assert it does NOT include a `--ignore=tests/observability/` or equivalent skip; OR (simpler) the test asserts that `pytest tests/observability/ -q` returns exit 0 (smoke-gate-compatible).

### Implementation for User Story 5

- [ ] T029 [US5] Add the no-net-new-`print()` baseline at `tests/observability/_baselines/hot_path_print_count.json`. After T021-T027 are GREEN, count `print()` occurrences in the hot-path file list and snapshot to JSON: `{"src/research_framework/pipeline/cycle_runner.py": 0, "src/research_framework/pipeline/orchestrator.py": 0, ...}`. The `test_no_net_new_print_in_hot_path_files` test (added in T021) compares actual count against this baseline.

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_hot_path_print_baseline_file_exists`
    - Behavior: Assert `_baselines/hot_path_print_count.json` exists, parses as JSON, and contains exactly the 7 hot-path file keys from FR-012.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T030 [US5] Final consolidation: ensure `tests/observability/test_log_surfaces.py` includes the FR-015 enumerated checks (a) through (e) as named test functions. Cross-reference checklist in the test file's module docstring. Add a comment at the top of the file: `# FR-015: this file is the regression guard. Surfaces verified: (a) root-logger config, (b) sentinel logger.info reaches stderr, (c) bridge.log creation, (d) line-buffered guarantee, (e) hot-path print baseline.`

  ### Testing Requirements

  _Authored 2026-05-29. Do not edit during implementation._

  - **Test 1**: `tests/observability/test_log_surfaces.py::test_fr015_checks_a_through_e_present`
    - Behavior: Use AST/`inspect.getmembers` to confirm 5 specific test function names exist in the same file (one per FR-015 enumeration item): `test_basicconfig_called_once_per_process`, `test_log_record_format_pinned`, `test_cycle_runner_creates_bridge_log_at_cycle_start`, `test_bridge_log_is_line_buffered`, `test_no_net_new_print_in_hot_path_files`. Fails if any are renamed/missing.
    - Tier: 2

  **TDD discipline**: required.

**Checkpoint**: US5 fully shipped. Future regressions on any of the 5 MVP surfaces fail this test file.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Sibling deliverable (strategy doc), lint, full suite, smoke gate, and the ship-stage doc-sync per CLAUDE.md.

- [ ] T031 [P] Write `docs/observability-strategy.md` mirroring `docs/testing-strategy.md`'s structure: TL;DR · Where this fits in the roadmap · The six-tier ladder (1. sidecar telemetry / 2. cycle summaries / 3. run-report / 4. vault status (v1.1) / 5. logger output / 6. bridge.log) · Decision tree (which tier to reach for given a question) · Anti-patterns · Composition with spec 022 quality harness · Regression discipline. ~250-400 lines.

- [ ] T032 Run `ruff check .` and `ruff format --check .`; assert zero new errors (baseline must stay at zero per CLAUDE.md). Fix any introduced violations.

- [ ] T033 Run `pytest -m "not e2e" -q` full suite; assert all tests pass (1278+ tests as of 0.3.2; this MVP adds ~25 new tests under `tests/observability/`). Fix any regressions.

- [ ] T034 Run `./build.sh` smoke gate; assert exit 0. Per ADR-0007 + FR-016, the observability tests are now part of the smoke set.

- [ ] T035 Ship-stage doc-sync per CLAUDE.md `/speckit.implement` checklist:
  - [ ] Set spec.md status header: `**Status**: SHIPPED 0.5.0-mvp` (or whatever version pyproject lands at)
  - [ ] Flip ROADMAP queue entry `#2` from `[~]` IN-FLIGHT to `[x]` shipped; add `(version, date)` reference; move to "Completed (recent)"; remove from Active
  - [ ] CHANGELOG.md `[Unreleased]` (or new version block): add `### Added` entry for observability v1 MVP referencing test path
  - [ ] CLAUDE.md "Recent Changes": add ship entry for spec 048 MVP
  - [ ] `pyproject.toml`: bump version per SemVer (MINOR — new feature surface)

**Checkpoint**: MVP ready for PR.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately. T002 + T003 parallelizable with T001.
- **Phase 2 (Foundational)**: Depends on Phase 1. T004/T006/T007 parallelizable; T005 depends on T004; T008 depends on T004-T007.
- **Phase 3 (US1)**: Depends on Phase 2 complete (especially T005's logger wiring).
- **Phase 4 (US2)**: Depends on Phase 3 complete (extends `BridgeLogWriter`).
- **Phase 5 (US3)**: Depends on Phase 2 complete (uses logger from T005); independent of Phase 3/4.
- **Phase 6 (US5)**: Depends on Phase 5 complete (needs the hot-path baseline from T029).
- **Phase 7 (Polish)**: Depends on Phases 3-6 complete.

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2.
- **US2 (P1)**: Depends on US1's `BridgeLogWriter` infrastructure.
- **US3 (P2)**: Starts after Phase 2, parallel to US1/US2.
- **US5 (P2)**: Depends on US3 (needs the migration snapshot).

### Parallel Opportunities

- T002 || T003 || T001 (Phase 1).
- T004 || T006 (Phase 2 test-side prep).
- T009 || T010 (Phase 3 tests).
- T015 || T016 (Phase 4 tests).
- T019 || T020 (Phase 5 tests).
- **T021 || T022 || T023 || T024 || T025 || T026 || T027** (Phase 5 implementation — 7 file migrations all independent).
- T031 || T032 (Phase 7 doc + lint).

### Within Each User Story

- Tests MUST be written and FAIL before implementation (foreman TDD-discipline flag REQUIRED on every implementation task).
- Tests in same-or-earlier commit as implementation.

---

## Implementation Strategy

### MVP-first (this entire tasks.md is the MVP)

The spec already cut to MVP scope. There is no smaller increment than what this file describes. Land Phases 1-7 sequentially; each Checkpoint is a valid "demo to user" state.

### Foreman discipline (ADR-0010)

Per `docs/foreman.md` § Parser grammar:
- Every implementation task has a `### Testing Requirements` block with one or more `- **Test N**: ` lines.
- The TDD-discipline flag is `required` on every implementation task — the verifier will check git commit ordering.
- `scripts/foreman/verify_test_coverage.py --tasks specs/048-observability-v1/tasks.md` MUST pass with exit 0 before PR opens.

### Open in PR

After T035, open PR with title `feat(spec-048): observability v1 MVP — runtime logging + bridge.log + hot-path print() migration`. Body references the spec + plan + this tasks.md. Closes the GitHub issue for spec 048 (number TBD when issue is created — likely via `/speckit-taskstoissues` after this lands or before).

---

## Notes

- [P] tasks = different files, no dependencies.
- Tests and implementation in same-or-earlier commit (foreman TDD-discipline required).
- Hot-path migration (T021-T027) is 7 parallel tasks but ALL must pass the same `test_no_net_new_print_in_hot_path_files` parametrized test.
- Non-hot-path `print()` calls (~45 remaining) stay UNTOUCHED in MVP. The allowlist convention (FR-014) ships in v1.1; do NOT add `# noqa: T201` comments in MVP.
- Do NOT add a `vault status` verb in MVP. FR-009/010/011 are explicitly deferred to v1.1.
- Do NOT add the one-line cycle health header to `cycle-NNN-summary.md` in MVP. FR-013 is deferred to v1.1.
- Avoid: vague tasks ("update logger logic"), cross-story dependencies, modifying tests after foreman verification has run.
