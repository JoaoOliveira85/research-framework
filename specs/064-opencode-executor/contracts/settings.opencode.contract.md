# Contract — `settings.opencode.yaml` peer profile

A drop-in alternative to `settings.yaml`, cloned from `settings.cursor.yaml` and
retargeted to opencode. Selected via `rv generate … --settings settings.opencode.yaml`
(copied into `{vault}/settings.yaml`).

## MUST

- `schema_version: 1`.
- `communication.mode: cli`.
- `default_executor`: `{ type: cli, runtime: opencode, model: <provider/model>, args: [...], skill: null, timeout_s, retry, on_fail }`.
- Be **bundled**: present at repo root, force-included into the wheel at
  `src/research_framework/_data/settings.opencode.yaml`, and added to the
  `dist-templates` bundle copy list in `build.sh` (parity with `settings.cursor.yaml`).
- Ship the **unattended approval posture** in `default_executor.args` (opencode
  analogue of cursor's `--force --approve-mcps`) so cron cycles don't block —
  WITHOUT relying on a full-disk posture (containment is `--dir`, auto-injected).
- Carry a `local_providers` key (default `[ollama, local]`) consumed by the cost
  classifier.
- Provide a `stages.*` map mirroring the cursor profile (cheap stages → a basic
  model/variant; default stages → the normal model; `model_router` upgrade →
  flagship), with a documented basic/normal/flagship tier table in the header
  comment.

## SHOULD

- Bias the **basic tier to a local Ollama model** (the cost pivot) with hosted
  models documented as one-line drop-ins.
- Header comment documents: `--model provider/model`, `--variant` effort, `--dir`
  containment, and the per-call cost-source behavior (local ⇒ `runtime`/$0;
  metered ⇒ `runtime_tokens`/estimated).

## MUST NOT

- Introduce a new settings schema key beyond `local_providers` + the existing
  executor fields (`variant`/`agent` already permitted as optional executor keys).
- Change `settings.yaml` / `settings.codex.yaml` / `settings.cursor.yaml`.

## Tests

- A bundling test asserts `settings.opencode.yaml` is in the wheel `_data/` and the
  bundle (parity with the existing cursor bundling test).
- A load test asserts `pipeline/settings.py` parses it and resolves
  `default_executor.runtime == "opencode"`.
