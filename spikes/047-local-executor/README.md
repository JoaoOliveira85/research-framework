# Local Agentic Executor Feasibility Spike (spec 047)

A self-contained, throwaway probe that answers **one** question on your own
machine:

> Can an off-the-shelf agentic CLI, driving a **remote local Ollama** model,
> reliably produce the two file-artifact shapes our research cycle depends on?

If yes, a local model can become a real **full-cycle executor** (not just the
"dispatch-only" Ollama HTTP backend shipped in 1.0.0rc5) and the working command
becomes a `settings.<engine>.yaml` profile. If no, a text-only backend would
need a heavier custom materializer/tool-loop and we re-scope before investing.

**Nothing here touches the framework.** Stdlib only, no new deps, writes only
under this directory (`_out/`, `.codex_home/` - both gitignored), never edits
your real `~/.codex/`, calls no company infra, uses no secrets.

## Why these two tests *are* the question

The framework's agentic stages succeed purely on **side-effect file writes**,
not stdout:

- **scout** must write one file, `_pipeline/cycles/cycle-NNN-scout.json`; the
  framework only checks it exists and parses it
  (`src/research_framework/pipeline/steps/scout.py`).
- **note-writer** must write **N** `.md` files under `data_vault/<folder>/`; the
  framework discovers them via a filesystem diff (`_discover_new_markdown_files`
  in `src/research_framework/pipeline/_helpers/_io.py`).

So the spike reproduces exactly those shapes:

- **Test A (scout)** - agent must write one `scout.json` with the right keys.
- **Test B (note-writer)** - agent must write 2 markdown files with valid YAML
  frontmatter under `data_vault/`.

A model that passes both drove a real agentic file-writing loop against a local
model - which is the whole ballgame.

## Prerequisites (on your personal machine)

1. **An agentic CLI** - `codex` (primary) or `opencode` (Plan B):
   - codex: `npm install -g @openai/codex` (or `brew install --cask codex`)
   - opencode: `curl -fsSL https://opencode.ai/install | bash`
2. **A reachable Ollama box** with the models pulled, e.g.:
   ```bash
   ollama pull qwen3:14b
   ollama pull gemma3:27b
   ollama pull llama3.3:70b
   ```
3. Python 3.11+ (stdlib only; PyYAML is used for stricter frontmatter checks
   *if* present, but is not required).

## Run it

Default sweep (qwen3:14b, gemma3:27b, llama3.3:70b) against the box at
`localhost`:

```bash
cd spikes/047-local-executor
python3 run_spike.py
```

Pick host/models/timeout explicitly:

```bash
python3 run_spike.py \
  --host localhost --port 11434 \
  --model qwen3:14b --model llama3.3:70b \
  --timeout 600
```

Plan B engine:

```bash
python3 run_spike.py --engine opencode --model qwen3:14b
```

Output: a PASS/FAIL matrix to the console, plus `_out/summary.json` and per-model
logs at `_out/<model>/{A,B}.log` showing exactly what the agent did.

## The codex + remote-Ollama gotcha (important)

codex's `--oss` flag and the reserved provider name `ollama` **force localhost
and ignore `base_url`** ([openai/codex#8240](https://github.com/openai/codex/issues/8240)).
The spike works around this automatically:

- it does **not** pass `--oss`;
- it writes an isolated `.codex_home/config.toml` defining a **custom**
  (non-reserved) provider `remoteoss` pointed at your box;
- it runs codex with `CODEX_HOME=.codex_home` so your real `~/.codex/` is
  untouched.

The generated config looks like:

```toml
model_provider = "remoteoss"

[model_providers.remoteoss]
name = "Remote Ollama (spike)"
base_url = "http://localhost:11434/v1"
wire_api = "chat"   # chat for qwen/gemma/llama; "responses" for gpt-oss
```

If codex complains about an unknown context window, add
`model_context_window` / `model_max_output_tokens` to that block (see the
inline comment the spike writes).

## Interpreting the result

- **VERDICT: PASS** - at least one model wrote both `scout.json` and the notes.
  A local model can be a full-cycle executor. The 047 next stage is then mostly:
  - a `settings.codex-oss.yaml` (or similar) profile (sketch below), and
  - small cost/telemetry wiring (treat local codex runs as `$0` + real tokens,
    like the existing Ollama HTTP path).
- **VERDICT: FAIL** - no model drove the loop / wrote files. Inspect the
  `_out/<model>/{A,B}.log` files. Expect weaker tool-callers (notably Gemma3) to
  print content instead of writing files. If even strong tool-callers (Qwen3,
  Llama3.3) fail, the agentic-CLI path is not viable and we pivot.

### What a PASS maps to (the real wiring, NOT done in this spike)

The framework already ships a `codex` runtime adapter (`_codex_cmd` in
`scripts/agent_call.py`) that injects `--cd <vault>` and `--model`. A local-codex
vault profile would look like (model tags per `settings.ollama.yaml`):

```yaml
communication:
  mode: cli
default_executor:
  type: cli
  runtime: codex
  model: qwen3:14b
  args: [exec, --sandbox, workspace-write, --ask-for-approval, never]
  timeout_s: 7200
stages:
  source_relevance: { model: qwen3:14b }
  scout:            { model: gemma3:27b, skill: scout }
  note_writer:      { model: gemma3:27b, skill: note-writer }
```

The one piece the 047 stage must add (and which this spike de-risks): pointing
codex at the **remote** provider. `_codex_cmd` does not set `CODEX_HOME` or a
provider today, so the stage would either export `CODEX_HOME`/config for the
custom `remoteoss` provider or document a user-level `~/.codex/config.toml`.
Per-stage model routing already works via `stages.*.model`; the dynamic
`model_router` auto-upgrade stays deferred.

## Cleanup

```bash
rm -rf _out .codex_home
```

## Troubleshooting

- **"UNREACHABLE"** - confirm the box is up and on the network:
  `curl http://localhost:11434/api/tags`.
- **"requested model ... not in the installed list"** - `ollama pull <model>`.
- **raw PASS but A/B FAIL** - the model generates text but won't drive the tool
  loop. Try a stronger tool-calling model (Qwen3/Llama3.3) or `--engine opencode`.
- **codex blocks on sandbox/approvals** - the spike already uses
  `--sandbox workspace-write --ask-for-approval never`; as a last resort codex
  also has `--dangerously-bypass-approvals-and-sandbox` (not used here by default).
- **70B is slow** - raise `--timeout` (an agentic loop is several round-trips).
