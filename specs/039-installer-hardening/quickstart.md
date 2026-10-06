# Quickstart — Installer Hardening (039)

How to exercise each behaviour the spec adds, and how to run its tests.

## Modes

```bash
# 1. Tarball happy path — install IN PLACE (no arg → TARGET = ROOT_DIR)
cd /path/to/extracted-bundle
./install.sh
#   → [install] installing in place at /path/to/extracted-bundle
#   → .venv/, rv, _pipeline/install_summary.json created HERE

# 2. Install/refresh a specific vault (the ./vault update path)
bash install.sh /home/me/my-vault
#   → scaffold + .venv land in /home/me/my-vault; the bundle dir is untouched
#   → wheel is still sourced from the bundle dir (ROOT_DIR)

# 3. Same via env var (positional wins if both set)
VAULT_DIR=/home/me/my-vault ./install.sh

# 4. Dry-run — show planned actions, mutate nothing
bash install.sh /tmp/preview --dry-run
#   → [dry-run] would create dir /tmp/preview
#   → [dry-run] would install research_framework-0.8.0-…whl into /tmp/preview/.venv
#   → exit 0 if the real install would succeed; non-zero if a blocker is detected
find /tmp/preview -type f | wc -l        # → 0 (SC-002)

# 5. Idempotent re-run — fast, non-destructive
bash install.sh /home/me/my-vault       # second time
#   → [install] vault already installed at /home/me/my-vault; refreshing scaffolds
#   → exits 0 in < 5 s (SC-003); customised files (027 user_authored) preserved

# 6. Linux missing-dependency case
bash install.sh /tmp/v                   # on a host without python3.11
#   → [FAIL] python3.11 missing — install via: apt install python3.11
#   → exit non-zero; install_summary.json exit_status = "failed"
```

## Inspect the audit record

```bash
cat /home/me/my-vault/_pipeline/install_summary.json | python -m json.tool
# fields per contracts/install-summary.contract.md
```

## Run the tests

```bash
# fast loop (subprocess + extract-fn harness; deterministic, no real network)
.venv/bin/python -m pytest tests/scripts/ -k install -q

# the opt-in slow real-install smoke (creates a real venv + pip install)
.venv/bin/python -m pytest tests/scripts/test_install_target_resolution.py -m slow -q
```

> Tests run via `.venv/bin/python` — the pyenv base python carries a stale
> editable install that fakes subprocess-test failures (see project memory
> `use-venv-python-not-pyenv`). Keep new tests **non-pty** to avoid the known
> sandbox pty-exhaustion seen in `test_install_sh_tty_handling.py`.

## What 009 consumes from here
Spec 009's `ubuntu-latest` CI job runs `bash install.sh tests/fixtures/quality/tech-lite --dry-run`
and asserts exit 0 + zero `[FAIL]` lines. The clean 039/009 split: **039** owns the
script behaviour above; **009** owns the CI job, `shellcheck`, and the repo-wide
`sed -i ''`/`~/Library` portability sweep.
