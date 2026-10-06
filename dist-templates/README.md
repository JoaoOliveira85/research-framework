# research-framework — distribution bundle

This is a self-contained installation bundle for the **research-framework** tool —
a knowledge-vault generator that turns a simple `research.spec.md` file into a
fully-structured, researchable Obsidian-compatible vault.

You do **not** need to clone the source repository. Everything the tool needs
to run is in this folder.

---

## Prerequisites

- **macOS or Linux** (Windows is not yet supported — use WSL if needed)
- **Python 3.11 or newer** available as `python3` on your `PATH`

Check with:

```bash
python3 --version
```

If Python 3.11+ isn't installed, grab it from [python.org](https://www.python.org/downloads/)
or your package manager (`brew install python@3.12` on macOS).

---

## Install

```bash
./install.sh
```

The installer runs a single linear flow:

1. Creates an isolated Python virtual environment inside this folder (`./.venv`)
2. Installs the bundled `research-framework` wheel
3. Creates a `./rv` shim so you can run the CLI without activating the venv
4. If `./research.spec.md` is missing, offers to draft one **inline** via the
   `vault-spec` agent skill on whichever CLI you have (`claude` or `codex`).
5. Once the spec exists, offers to run `./generate.sh` with the default
   settings right there.

In other words: one `./install.sh` invocation can take you from a fresh
download to a generated vault without ever editing a file or re-running
anything. Total size after install: ~30 MB. No system-level changes.

Pass `--non-interactive` (or set `RV_NONINTERACTIVE=1`) to skip the wizard.

---

## Quickstart — generate your first vault

The recommended path is `./install.sh` → answer prompts. If you'd rather
set things up manually, or you want to re-run against an existing spec:

1. Set `output_dir:` in `settings.yaml` to the path you want the vault to
   live at (or leave it `null` and pass `--output` explicitly later).

2. Author the spec. Copy the example and edit:

   ```bash
   cp examples/research.spec.md research.spec.md
   ```

   See the [research.spec.md spec](./examples/research.spec.md) for a commented
   walkthrough of every field.

3. Generate with zero arguments:

   ```bash
   ./generate.sh
   ```

   This uses `./research.spec.md` and `./settings.yaml` from the bundle
   directory. If you prefer the classic positional form, it still works:

   ```bash
   ./generate.sh my-spec.md ~/Documents/my-vault
   ```

   The tool will:
   - Parse and validate your spec
   - Scaffold the vault directory structure
   - Copy the spec file in so the vault is self-contained
   - Run the research cycle (interactive; follow on-screen prompts)
   - Commit the result to a fresh git repository at the vault root

4. Open the vault in Obsidian:

   ```bash
   open ~/Documents/my-vault/data_vault
   ```

   Or point any Markdown-aware editor at the `data_vault/` subfolder.

---

## Updating an existing vault

Every generated vault carries its own `research.spec.md`. To run another
research pass on it:

```bash
./update.sh                            # zero-arg: reads output_dir from settings.yaml
./update.sh ~/Documents/my-vault       # explicit path also works
```

This runs in `--resume` mode, so already-covered topics are skipped and the
budget only pays for new work.

---

## Dry-run / preview

Any of the wrappers accept passthrough flags. To validate a spec and scaffold
the folders without actually running research:

```bash
./generate.sh --dry-run --skip-gate
```

---

## Switching runtimes

Every vault bakes a `settings.yaml` that tells the orchestrator which agent
runtime to use for each stage. Six profiles ship in the box; each one's
header comment documents its tier → model map and prerequisites:

| File                          | Runtime                 | When to pick it                                                       |
|-------------------------------|-------------------------|-----------------------------------------------------------------------|
| `settings.yaml` *(default)*   | `claude` CLI            | You have Anthropic credits / tokens available.                        |
| `settings.codex.yaml`         | `codex` CLI             | No Claude tokens, or you prefer OpenAI.                               |
| `settings.cursor.yaml`        | `cursor-agent` CLI      | Flat-rate Cursor billing (spec 052).                                  |
| `settings.cursor-claude.yaml` | `cursor-agent` + Claude | Cursor's `--workspace` containment paired with Claude models.         |
| `settings.opencode.yaml`      | `opencode` CLI          | Any provider through one agentic executor — `--model ollama/<model>` runs a local model at $0 (spec 064). |
| `settings.ollama.yaml`        | Ollama over HTTP        | Fully local, MCP-free, no vendor CLI — dispatch-only (spec 047 v1): a local model must complete the autonomous stages for a full cycle, which spec 065 records is not yet the case for 27–30B models. |

A local / self-hosted model path is always supported (the last two rows);
what a given local model can *complete* is tracked in spec 065.

The `--settings` flag now takes a **file path**, not an alias. To run on
Codex, point at the bundled profile:

```bash
./generate.sh --settings settings.codex.yaml
```

You can of course also pass a hand-authored YAML file:

```bash
./generate.sh --settings ./my-custom-settings.yaml
```

The chosen file is copied into the vault as `settings.yaml` at generation
time, so the vault stays self-contained — swapping profiles on an existing
vault is just `cp settings.codex.yaml <vault>/settings.yaml`.

### Setting the output path in settings.yaml

Instead of passing `--output` on every run, set `output_dir:` at the top
of `settings.yaml` (or `settings.codex.yaml`):

```yaml
output_dir: ~/Documents/my-vault
```

Then `./generate.sh` (and `./update.sh`) can run with zero arguments and
will resolve the vault from that setting. Relative paths are resolved
against the settings file's parent directory, so a `settings.yaml` placed
next to a spec stays portable.

---

## What's inside this bundle

| File / folder            | Purpose                                                   |
|--------------------------|-----------------------------------------------------------|
| `install.sh`             | One-time installer                                        |
| `generate.sh`            | Generate a new vault                                      |
| `update.sh`              | Re-run research on an existing vault                      |
| `rv`                     | Shim: `./rv <any research-framework args>`                    |
| `research_framework-*.whl`   | The Python package — installed into `./.venv` by install  |
| `scripts/`               | Validation + helper scripts copied into every vault       |
| `templates/`             | Jinja2 templates for vault scaffolding                    |
| `.agents/skills/`        | Agent skill files consumed by the research orchestrator   |
| `settings.yaml`          | Default (Claude) settings profile                         |
| `settings.*.yaml`        | The other five runtime profiles (`codex`, `cursor`, `cursor-claude`, `opencode`, `ollama`) — see "Switching runtimes" above |
| `examples/`              | Example `research.spec.md` you can copy and edit          |
| `VERSION`                | Build version stamp                                       |

---

## Troubleshooting

**`python3: command not found`** — Install Python 3.11+ (`brew install python@3.12`).

**`virtualenv not found`** — Run `./install.sh` first.

**`research_framework-*.whl` missing** — The bundle is corrupted. Re-download.

**Installation complains about SSL / certificates** — Your system Python
certificates are stale. On macOS, run `/Applications/Python\ 3.12/Install\ Certificates.command`.

---

## Uninstall

```bash
rm -rf ./.venv ./rv
```

Or just delete this entire folder. Nothing is installed outside of it.

---

## Source code

This bundle is a build artefact. If you want to read or modify the source,
head over to the [upstream repository](https://github.com/JoaoOliveira85/research-framework).
