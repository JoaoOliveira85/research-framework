#!/usr/bin/env python3
"""Local agentic executor feasibility spike (spec 047 next stage).

Question this answers, on YOUR machine, with nothing from the framework:

    Can an off-the-shelf agentic CLI, driving a *remote* local Ollama model,
    reliably produce the two file-artifact shapes our research cycle depends on?

      * Test A (scout contract)      -> write ONE json file to a target path.
      * Test B (note-writer contract)-> write N markdown files (with YAML
                                        frontmatter) into a folder.

The framework's agentic stages succeed purely on side-effect file writes, not
stdout (scout: existence+parse of cycle-NNN-scout.json; note-writer: a
filesystem diff over data_vault/). So if a model+engine passes A and B here, it
can serve as a full-cycle local executor and the working command becomes a
settings.<engine>.yaml profile. If it fails, a text-only backend would need a
heavier custom materializer/tool-loop and we'd reconsider scope.

Stdlib only. Innocuous: writes only under this spike dir (_out/, .codex_home/),
never touches your real ~/.codex/, calls no company infra, uses no secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
OUT_DIR = SPIKE_DIR / "_out"
CODEX_HOME = SPIKE_DIR / ".codex_home"

# Optional: stricter frontmatter parse if PyYAML happens to be importable.
# The spike does NOT depend on it (your personal machine may not have it).
try:
    import yaml  # type: ignore

    _HAVE_YAML = True
except Exception:  # pragma: no cover - environment dependent
    yaml = None  # type: ignore
    _HAVE_YAML = False


# --------------------------------------------------------------------------- #
# Prompts - deliberately tiny, but the exact two shapes the cycle needs.
# --------------------------------------------------------------------------- #

PROMPT_SCOUT = """\
You are an automated agent operating inside a workspace directory. You have
tools to create and edit files. Use them now.

Create a single file named `scout.json` in the current working directory.
Its contents MUST be a valid JSON object with EXACTLY these keys:
  - "schema_version": the string "2.0"
  - "phase": the string "scout"
  - "topics": an array of exactly 3 short topic strings (any subject)

Write ONLY that file. Do NOT print the JSON to the screen. Do NOT create any
other files. Once `scout.json` exists on disk, you are done; stop.
"""

PROMPT_NOTES = """\
You are an automated agent operating inside a workspace directory. You have
tools to create and edit files. Use them now.

Create EXACTLY two Markdown files (create the `data_vault` directory if needed):
  - `data_vault/note_one.md`
  - `data_vault/note_two.md`

Each file MUST begin with a YAML frontmatter block delimited by lines that
contain only `---`, with these keys:
  - title: a short title string
  - note_type: concept
  - source_urls: a YAML list containing one URL string
After the closing `---`, write 2 to 3 sentences of plain text about the title.

Write ONLY those two files. Do NOT print them. Do NOT create other files. Once
both files exist on disk, you are done; stop.
"""


# --------------------------------------------------------------------------- #
# Small result types
# --------------------------------------------------------------------------- #


@dataclass
class StepResult:
    ok: bool
    detail: str = ""
    duration_s: float = 0.0


@dataclass
class ModelRow:
    model: str
    raw: StepResult = field(default_factory=lambda: StepResult(False, "not run"))
    test_a: StepResult = field(default_factory=lambda: StepResult(False, "not run"))
    test_b: StepResult = field(default_factory=lambda: StepResult(False, "not run"))

    @property
    def full_cycle_ok(self) -> bool:
        return self.test_a.ok and self.test_b.ok


# --------------------------------------------------------------------------- #
# HTTP helpers (raw Ollama connectivity - engine independent)
# --------------------------------------------------------------------------- #


def _http_get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local LAN
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local LAN
        return json.loads(resp.read().decode("utf-8"))


def check_tags(host: str, port: int, timeout: float) -> tuple[bool, list[str], str]:
    """Confirm the box is reachable; return (ok, available_model_names, detail)."""
    url = f"http://{host}:{port}/api/tags"
    try:
        obj = _http_get_json(url, timeout)
    except urllib.error.URLError as exc:
        return False, [], f"cannot reach {url}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, [], f"cannot reach {url}: {exc}"
    names: list[str] = []
    for m in obj.get("models") or []:
        name = m.get("name") or m.get("model")
        if name:
            names.append(str(name))
    return True, names, f"reachable; {len(names)} model(s) installed"


def check_generation(host: str, port: int, model: str, timeout: float) -> StepResult:
    """Tiny chat completion to confirm the model actually generates text."""
    url = f"http://{host}:{port}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "stream": False,
    }
    t0 = time.time()
    try:
        obj = _http_post_json(url, payload, timeout)
    except Exception as exc:  # noqa: BLE001
        return StepResult(False, f"generation request failed: {exc}", time.time() - t0)
    text = ""
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        text = (choices[0].get("message") or {}).get("content") or ""
    if text.strip():
        return StepResult(True, f"got {len(text.strip())} chars", time.time() - t0)
    return StepResult(False, "empty completion", time.time() - t0)


# --------------------------------------------------------------------------- #
# Subprocess runner with process-tree-safe timeout
# --------------------------------------------------------------------------- #


def run_subprocess(
    cmd: list[str],
    *,
    input_text: str,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
) -> tuple[int | None, str, str, bool]:
    """Run cmd, feeding input_text on stdin. Returns (rc, out, err, timed_out).

    Uses a new session so a timeout kills the whole process tree (codex/opencode
    spawn children; a plain ``subprocess`` timeout would leak them).
    """
    try:
        proc = subprocess.Popen(  # noqa: S603 - we control argv
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        return None, "", f"binary not found: {exc}", False
    try:
        out, err = proc.communicate(input=input_text, timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            proc.kill()
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            out, err = "", ""
        return None, out, err, True


# --------------------------------------------------------------------------- #
# Engine adapters
# --------------------------------------------------------------------------- #


def engine_available(engine: str) -> tuple[bool, str]:
    rc, out, err, _ = run_subprocess(
        [engine, "--version"],
        input_text="",
        cwd=SPIKE_DIR,
        env=dict(os.environ),
        timeout=20,
    )
    if rc is None and not (out or err):
        return False, "binary not found on PATH"
    if rc == 0:
        return True, (out or err).strip().splitlines()[0] if (out or err) else "ok"
    # Some CLIs print version to stderr / exit non-zero; treat any output as present.
    if out or err:
        return True, (out or err).strip().splitlines()[0]
    return False, "binary not found on PATH"


def ensure_codex_home(host: str, port: int, wire_api: str) -> None:
    """Write an ISOLATED codex config pointing at the remote Ollama.

    Critical gotcha (openai/codex#8240): codex's ``--oss`` flag and the reserved
    provider name ``ollama`` force localhost and ignore base_url. The workaround
    is a CUSTOM, non-reserved provider name + a profile/top-level model_provider,
    and NOT passing ``--oss``. We scope it all to CODEX_HOME under this spike dir
    so your real ~/.codex/ is never touched.
    """
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    config = (
        "# Auto-generated by run_spike.py - isolated, safe to delete.\n"
        'model_provider = "remoteoss"\n'
        "\n"
        "[model_providers.remoteoss]\n"
        'name = "Remote Ollama (spike)"\n'
        f'base_url = "http://{host}:{port}/v1"\n'
        f'wire_api = "{wire_api}"\n'
        "# If codex complains about an unknown context window for your model,\n"
        "# add e.g.  model_context_window = 32768  and  model_max_output_tokens = 8192\n"
    )
    (CODEX_HOME / "config.toml").write_text(config, encoding="utf-8")


def build_codex_cmd(model: str, workdir: Path) -> list[str]:
    # No --oss (see ensure_codex_home). Prompt is piped on stdin via the "-" arg.
    return [
        "codex",
        "exec",
        "-C",
        str(workdir),
        "--sandbox",
        "workspace-write",
        "--ask-for-approval",
        "never",
        "-m",
        model,
        "-",
    ]


def build_opencode_cmd(model: str) -> list[str]:
    # Plan B / best-effort - opencode is provider-agnostic and natively supports
    # Ollama. Exact flags vary by version; adjust if yours differs. Prompt is
    # passed as a positional task (opencode run has no stdin contract here).
    return ["opencode", "run", "--model", f"ollama/{model}"]


def run_engine(
    engine: str,
    model: str,
    workdir: Path,
    prompt: str,
    *,
    host: str,
    port: int,
    timeout: float,
    log_path: Path,
) -> tuple[int | None, bool]:
    """Run one agentic task. Returns (returncode, timed_out). Logs are saved."""
    env = dict(os.environ)
    if engine == "codex":
        cmd = build_codex_cmd(model, workdir)
        env["CODEX_HOME"] = str(CODEX_HOME)
        stdin_text = prompt
    elif engine == "opencode":
        cmd = build_opencode_cmd(model) + [prompt]
        # Best-effort remote pointer for the ollama provider.
        env.setdefault("OLLAMA_HOST", f"http://{host}:{port}")
        stdin_text = ""
    else:  # pragma: no cover - argparse restricts choices
        raise ValueError(f"unknown engine: {engine}")

    rc, out, err, timed_out = run_subprocess(
        cmd, input_text=stdin_text, cwd=workdir, env=env, timeout=timeout
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        f"$ {' '.join(cmd)}\n"
        f"(cwd={workdir})\n"
        f"(timed_out={timed_out}, returncode={rc})\n"
        f"\n===== STDOUT =====\n{out}\n\n===== STDERR =====\n{err}\n",
        encoding="utf-8",
    )
    return rc, timed_out


# --------------------------------------------------------------------------- #
# Validators - mirror the real cycle contracts
# --------------------------------------------------------------------------- #


def validate_scout(workdir: Path) -> StepResult:
    path = workdir / "scout.json"
    if not path.exists():
        return StepResult(False, "scout.json was not written")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return StepResult(False, f"scout.json is not valid JSON: {exc}")
    missing = [k for k in ("schema_version", "phase", "topics") if k not in obj]
    if missing:
        return StepResult(False, f"missing keys: {missing}")
    topics = obj.get("topics")
    if not isinstance(topics, list) or len(topics) != 3:
        return StepResult(False, f"topics must be a 3-element list, got {topics!r}")
    return StepResult(True, "valid scout.json with 3 topics")


_FM_KEYS = ("title", "note_type", "source_urls")


def _frontmatter_ok(text: str) -> tuple[bool, str]:
    if not text.lstrip().startswith("---"):
        return False, "no opening '---'"
    # Split off the first fenced block.
    body = text.lstrip()
    parts = body.split("\n")
    if parts[0].strip() != "---":
        return False, "first line is not '---'"
    end = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end = i
            break
    if end is None:
        return False, "no closing '---'"
    block = "\n".join(parts[1:end])
    if _HAVE_YAML:
        try:
            data = yaml.safe_load(block) or {}
        except Exception as exc:  # noqa: BLE001
            return False, f"frontmatter not parseable YAML: {exc}"
        missing = [k for k in _FM_KEYS if k not in data]
        if missing:
            return False, f"missing frontmatter keys: {missing}"
        if not isinstance(data.get("source_urls"), list):
            return False, "source_urls is not a list"
        return True, "valid frontmatter"
    # Lightweight stdlib fallback - key presence only.
    missing = [k for k in _FM_KEYS if not re.search(rf"(?m)^{k}\s*:", block)]
    if missing:
        return False, f"missing frontmatter keys: {missing}"
    return True, "frontmatter keys present (no yaml lib for strict check)"


def validate_notes(workdir: Path) -> StepResult:
    dv = workdir / "data_vault"
    if not dv.is_dir():
        return StepResult(False, "data_vault/ was not created")
    md_files = sorted(dv.rglob("*.md"))
    if len(md_files) < 2:
        return StepResult(False, f"expected >=2 .md files, found {len(md_files)}")
    good = 0
    problems: list[str] = []
    for f in md_files:
        ok, why = _frontmatter_ok(f.read_text(encoding="utf-8"))
        if ok:
            good += 1
        else:
            problems.append(f"{f.name}: {why}")
    if good >= 2:
        return StepResult(True, f"{good}/{len(md_files)} notes valid")
    return StepResult(False, "; ".join(problems) or "no valid notes")


# --------------------------------------------------------------------------- #
# Per-model driver
# --------------------------------------------------------------------------- #


def _safe(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)


def run_model(
    engine: str,
    model: str,
    *,
    host: str,
    port: int,
    timeout: float,
) -> ModelRow:
    row = ModelRow(model=model)
    model_out = OUT_DIR / _safe(model)

    print(f"\n=== model: {model} ===", flush=True)

    # raw generation (engine-independent)
    print("  [raw] tiny chat completion ...", flush=True)
    row.raw = check_generation(host, port, model, timeout=min(timeout, 120))
    print(f"        {'PASS' if row.raw.ok else 'FAIL'} - {row.raw.detail}", flush=True)

    # Test A - scout single-JSON contract
    work_a = model_out / "A"
    if work_a.exists():
        shutil.rmtree(work_a)
    work_a.mkdir(parents=True)
    print("  [A]  scout: write one scout.json ...", flush=True)
    t0 = time.time()
    rc, timed_out = run_engine(
        engine,
        model,
        work_a,
        PROMPT_SCOUT,
        host=host,
        port=port,
        timeout=timeout,
        log_path=model_out / "A.log",
    )
    res_a = validate_scout(work_a)
    res_a.duration_s = time.time() - t0
    if timed_out:
        res_a = StepResult(False, "engine timed out", res_a.duration_s)
    row.test_a = res_a
    print(
        f"        {'PASS' if res_a.ok else 'FAIL'} - {res_a.detail} "
        f"({res_a.duration_s:.0f}s)",
        flush=True,
    )

    # Test B - note-writer multi-file contract
    work_b = model_out / "B"
    if work_b.exists():
        shutil.rmtree(work_b)
    work_b.mkdir(parents=True)
    print("  [B]  note-writer: write 2 notes under data_vault/ ...", flush=True)
    t0 = time.time()
    rc, timed_out = run_engine(
        engine,
        model,
        work_b,
        PROMPT_NOTES,
        host=host,
        port=port,
        timeout=timeout,
        log_path=model_out / "B.log",
    )
    res_b = validate_notes(work_b)
    res_b.duration_s = time.time() - t0
    if timed_out:
        res_b = StepResult(False, "engine timed out", res_b.duration_s)
    row.test_b = res_b
    print(
        f"        {'PASS' if res_b.ok else 'FAIL'} - {res_b.detail} "
        f"({res_b.duration_s:.0f}s)",
        flush=True,
    )

    return row


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _cell(s: StepResult) -> str:
    return "PASS" if s.ok else "FAIL"


def print_matrix(rows: list[ModelRow], engine: str) -> None:
    print("\n" + "=" * 64)
    print(f"SUMMARY  (engine={engine})")
    print("=" * 64)
    header = f"{'model':<22} {'raw':<6} {'A:scout':<9} {'B:notes':<9} {'verdict'}"
    print(header)
    print("-" * len(header))
    for r in rows:
        verdict = "FULL-CYCLE OK" if r.full_cycle_ok else "-"
        print(
            f"{r.model:<22} {_cell(r.raw):<6} {_cell(r.test_a):<9} "
            f"{_cell(r.test_b):<9} {verdict}"
        )
    print("-" * len(header))
    winners = [r.model for r in rows if r.full_cycle_ok]
    if winners:
        print(
            "\nVERDICT: PASS. These model(s) drove the full agentic cycle "
            f"(A+B): {', '.join(winners)}."
        )
        print(
            "         => a local model CAN be a full-cycle executor. The working\n"
            "            codex command becomes the settings.<engine>.yaml args\n"
            "            (runtime: codex, model: <winner>, args: [exec, --sandbox,\n"
            "            workspace-write, --ask-for-approval, never], + the remote\n"
            "            provider in config). Per-stage routing already works via\n"
            "            stages.*.model; dynamic model_router upgrade stays deferred."
        )
    else:
        print(
            "\nVERDICT: FAIL. No model both wrote scout.json AND the notes.\n"
            "         => a text-only backend would need a heavier custom\n"
            "            materializer / tool-loop. Re-scope before investing.\n"
            "         Inspect _out/<model>/{A,B}.log to see what the agent did."
        )
    print(f"\nLogs + artifacts: {OUT_DIR}")


def write_summary_json(rows: list[ModelRow], engine: str, meta: dict) -> None:
    payload = {
        "engine": engine,
        "meta": meta,
        "results": [
            {
                "model": r.model,
                "raw": {"ok": r.raw.ok, "detail": r.raw.detail},
                "test_a_scout": {
                    "ok": r.test_a.ok,
                    "detail": r.test_a.detail,
                    "duration_s": round(r.test_a.duration_s, 1),
                },
                "test_b_notes": {
                    "ok": r.test_b.ok,
                    "detail": r.test_b.detail,
                    "duration_s": round(r.test_b.duration_s, 1),
                },
                "full_cycle_ok": r.full_cycle_ok,
            }
            for r in rows
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Feasibility spike: can a local Ollama model drive our agentic cycle?",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--engine", choices=["codex", "opencode"], default="codex")
    p.add_argument(
        "--host", default="localhost", help="Ollama host (default: %(default)s)"
    )
    p.add_argument("--port", type=int, default=11434)
    p.add_argument(
        "--model",
        dest="models",
        action="append",
        help="Model tag (repeatable). Default sweep: qwen3:14b, gemma3:27b, llama3.3:70b",
    )
    p.add_argument(
        "--codex-wire-api",
        choices=["chat", "responses"],
        default="chat",
        help="codex wire API: 'chat' for qwen/gemma/llama, 'responses' for gpt-oss",
    )
    p.add_argument("--timeout", type=float, default=300.0, help="per-task seconds")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    models = args.models or ["qwen3:14b", "gemma3:27b", "llama3.3:70b"]

    print("=" * 64)
    print("Local Agentic Executor Feasibility Spike (spec 047)")
    print("=" * 64)
    print(f"engine        : {args.engine}")
    print(f"ollama        : http://{args.host}:{args.port}")
    print(f"models        : {', '.join(models)}")
    if args.engine == "codex":
        print(f"codex wire_api: {args.codex_wire_api}")
    print(f"timeout/task  : {args.timeout:.0f}s")
    print(f"strict yaml   : {'yes' if _HAVE_YAML else 'no (key-presence fallback)'}")
    print(f"output dir    : {OUT_DIR}")

    # 1) engine present?
    ok, ver = engine_available(args.engine)
    if not ok:
        print(f"\nERROR: '{args.engine}' not found on PATH ({ver}).")
        if args.engine == "codex":
            print(
                "  Install: npm install -g @openai/codex   (or: brew install --cask codex)"
            )
        else:
            print("  Install: curl -fsSL https://opencode.ai/install | bash")
        return 2
    print(f"\n{args.engine} version: {ver}")

    # 2) box reachable?
    reach_ok, names, detail = check_tags(args.host, args.port, timeout=15)
    print(f"ollama /api/tags: {'OK' if reach_ok else 'UNREACHABLE'} - {detail}")
    if not reach_ok:
        print("\nERROR: cannot reach the Ollama box. Is it running and on the network?")
        print(f"  Try:  curl http://{args.host}:{args.port}/api/tags")
        return 2
    if names:
        print(f"  installed models: {', '.join(names)}")
    for m in models:
        if names and m not in names:
            print(
                f"  WARNING: requested model '{m}' is not in the installed list; "
                f"pull it first (`ollama pull {m}`) or it will FAIL."
            )

    # 3) codex isolated config
    if args.engine == "codex":
        ensure_codex_home(args.host, args.port, args.codex_wire_api)
        print(f"  wrote isolated codex config: {CODEX_HOME / 'config.toml'}")

    # 4) run the matrix
    rows = [
        run_model(args.engine, m, host=args.host, port=args.port, timeout=args.timeout)
        for m in models
    ]

    meta = {
        "host": args.host,
        "port": args.port,
        "codex_wire_api": args.codex_wire_api if args.engine == "codex" else None,
        "timeout_s": args.timeout,
        "strict_yaml": _HAVE_YAML,
    }
    write_summary_json(rows, args.engine, meta)
    print_matrix(rows, args.engine)

    return 0 if any(r.full_cycle_ok for r in rows) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
