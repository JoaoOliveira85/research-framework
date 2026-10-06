# Phase 0 Research — Installer Hardening (039)

Decisions resolving the spec's open questions + the spec-vs-code reconciliation
surfaced when reading the shipped `dist-templates/install.sh` and the `./vault`
shim. Each decision: **what**, **why**, **alternatives rejected**.

## D1 — `TARGET` resolution: `$1` > `${VAULT_DIR}` > `ROOT_DIR`
**What**: Resolve exactly one target directory at the top of the script (right after
arg-parse): positional `$1` wins, else `${VAULT_DIR}`, else `ROOT_DIR` (script's own
dir). `mkdir -p "$TARGET"` if absent. No-arg ⇒ install-in-place.
**Why**: Two real call-sites. (a) Tarball happy path — user extracts the bundle and
runs `./install.sh` with no arg; that must install in place. (b) `./vault update`
runs `bash "${TMPDIR_UPDATE}/install.sh" "${VAULT_DIR}"` (`templates/vault-script.sh.j2`)
— that must operate on the vault. A single precedence chain serves both.
**Rejected**: *Hard-break on no-arg* (the original clarify answer) — would break every
tarball install, since no-arg is the primary flow, not an error. Corrected mid-clarify
after the code read.

## D2 — Wheel sourced from `ROOT_DIR`; everything else written to `TARGET`
**What**: `ROOT_DIR` stays the anchor for *bundle inputs* — the `research_framework-*.whl`
glob (line 186), the `.agents/skills/` preflight, the seed `examples/`/scaffold sources.
`TARGET` is the destination for *outputs* — `.venv/`, `rv`, `research.spec.md`, scaffold,
`_pipeline/install_summary.json`. The only `cd` change: `cd "${ROOT_DIR}"` (line 25) →
`cd "${TARGET}"`.
**Why**: In `./vault update`, the wheel lives in the downloaded tmpdir (`ROOT_DIR`) while
the vault is elsewhere (`TARGET`). Conflating them is exactly the F2 bug.
**Rejected**: *Copy the wheel into `TARGET` first* — wasteful and pollutes the vault with
a build artifact; pip can install directly from the `ROOT_DIR` path.

## D3 — Dependency tiers = **Mixed** (Q1)
**What**: MANDATORY `python ≥ 3.11` / `git` / `curl` (miss → non-zero exit + exact install
command); WARN `rsync` / `claude` (miss → warn + continue, recorded in `degraded_modes`);
INFORMATIONAL `codex` / `weasyprint` / `gh` (miss → info log).
**Why**: `python`/`git`/`curl` are load-bearing for venv + wheel + fetch. `claude`/`codex`
are needed only for the optional onboarding chat (already gracefully handled). `weasyprint`
is only for spec-040 PDF export; `gh` only for issue hygiene. Blocking on those would deny
a perfectly good headless install.
**Rejected**: *Strict* (every miss blocks) — denies degraded-but-useful installs.
*Permissive* (nothing blocks) — lets a python-less box limp to a confusing pip failure.

## D4 — `--dry-run` = global guard + a `run()`/`would()` wrapper; CLI check = presence-only (Q2)
**What**: Parse `--dry-run` (and honour `INSTALL_DRY_RUN=1`, propagated to children). Every
mutating op (`mkdir`, `cp`, `python -m venv`, `pip install`, file writes, `chmod`) routes
through a wrapper that, in dry-run, prints `[dry-run] would <action> <target>` instead of
executing. CLI validation uses `command -v claude` / `command -v codex` only — **no
invocation** (no `--version`).
**Why**: A single guard keeps the real and dry paths from diverging. Presence-check is
cheap, deterministic, and decoupled from CLI-invocation contracts that drift; a
present-but-broken CLI surfaces at real-run time. Dry-run is also the primary *test* surface.
**Rejected**: *Invoke `--version`* (Q2 alt) — couples dry-run to external CLI output that
changes across versions; flaky in CI. *Skip CLI checks entirely* — loses a useful warning.

## D5 — OS + package-manager detection
**What**: `uname -s` → `Darwin`|`Linux`; anything else → exit **3** "unsupported OS". Probe
package managers in precedence order: macOS → `brew`; Linux → `apt` > `dnf` > `pacman` >
`apk`, with `brew` as a final option if present (Homebrew-on-Linux is real). No recognised
manager → print raw copy-paste install commands (FR-007), never silently fail.
**Why**: `uname -s` is universally available and stable. The precedence matches distro
ubiquity. Raw-commands fallback keeps Alpine/minimal hosts unblocked.
**Rejected**: Parsing `/etc/os-release` — more code, and the manager probe (`command -v apt`)
is a more direct signal of what's actually installed.

## D6 — Idempotency strategy (two-step, 027-coupled)
**What**: On re-run, detect an existing install (`TARGET/.venv` present **and**
`TARGET/_pipeline/install_summary.json` present) → take the fast path: skip venv creation,
let `pip` short-circuit already-satisfied wheels, refresh scaffold **only** for files not
flagged `user_authored`, update `install_summary.json`, exit 0 in < 5 s. **Step 1 (this
spec)**: the fast-exit + pip-skip + summary-update. **Step 2 (gated on spec 027)**: honour
the `user_authored` vs `user_customizable` preservation flags so customised files are never
clobbered.
**Why**: Idempotency is the foundation of `./vault update` and unattended/CI installs. The
preservation half genuinely depends on 027's flag taxonomy, so splitting avoids inventing a
parallel one.
**Rejected**: *Block all overwrites on re-run* — too conservative; legit scaffold updates
(the point of `./vault update`) wouldn't land. *Always overwrite* — destroys user edits.

## D7 — `install_summary.json` (FR-013)
**What**: Atomic-write `TARGET/_pipeline/install_summary.json` at the end of every run
(real or dry). Fields: `framework_version`, `installed_at` (ISO-8601 UTC), `os`
(`darwin`/`linux`), `os_version`, `python_version`, `package_manager`, `target_dir`,
`root_dir`, `dry_run` (bool), `warnings` (list), `degraded_modes` (list of dep names that
warned), `exit_status` (`ok`/`degraded`/`failed`). Re-run overwrites (idempotent), written
via a temp-file + `mv` rename so a crash never leaves a half-file. Full schema +
example in `contracts/install-summary.contract.md`.
**Why**: A machine-readable install audit log that `./vault update` (027) reads for upgrade
decisions and 009's CI asserts against.
**Rejected**: Appending a log history array — `./vault update` only needs the *current*
state; git history already records the timeline once the vault is committed.

## D8 — Bash testing strategy
**What**: Reuse the **extract-function-into-sandbox-bash** harness from
`test_install_venv_staleness.py` (it greps a `fn() { … }` block out of `install.sh` and runs
it in isolation). Add per-FR pytest modules. The `--dry-run` path is asserted end-to-end
(it makes no real changes, so `find "$TARGET" -type f | wc -l` == 0 is the oracle). One
**opt-in, slow-marked** real-install smoke (`@pytest.mark.slow`) covers the genuine
venv+wheel happy path. `shellcheck` is **spec 009's** lint gate, referenced not duplicated.
**Why**: Keeps the fast loop fast and deterministic; avoids real network/pip in unit tests;
matches the repo's proven pattern. Non-pty to dodge the known sandbox pty-exhaustion.
**Rejected**: `bats` — a new dev dependency for no gain over the existing pytest pattern.

## D9 — Preserve existing behaviours (regression inventory)
**What**: The refactor MUST NOT disturb: (a) the v0.2.24 pre-redirect **TTY-state capture**
(`RV_*_IS_TTY`); (b) the crash-safe `install.log` **tee**; (c) the spec-051 **stale-venv
rebuild** (`_detect_stale_venv`) + **post-install version sanity check**; (d) the
`check-skills` **preflight**; (e) the **onboarding wizard** + settings sniffers. These all
key off `ROOT_DIR`/the venv and remain anchored there; `TARGET` only redirects the install
*destination*.
**Why**: Each encodes a hard-won fix; silently regressing one repeats a shipped incident.
The two existing install tests (`venv_staleness`, `tty_handling`) are the tripwire and MUST
stay green.
**Rejected**: A from-scratch rewrite of `install.sh` — would risk all of the above for no
benefit; the change is surgical (TARGET resolution + redirect of write-targets).
