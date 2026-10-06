"""spec-019 / 0.2.29 — install.sh wizard MUST skip questions whose answers
are already declared in settings.yaml / research.spec.md.

Background:

User trial-run report after the 0.2.28 release::

    Which agent runtime for generation? [claude/codex] (Enter=claude) codex

The user had already set ``default_executor.runtime: codex`` in
``settings.yaml`` (which was bundled into the install dir). Asking again
violates the wizard's golden rule: ``never ask for what you can infer
from the artifacts already on disk``. Same applies to the destination
folder — settings ``output_dir`` and spec ``location`` both encode this.

These tests don't run ``install.sh`` end-to-end (that needs a real
``./research_framework-*.whl`` and a Python venv). They:

1. Lock in the shell-side helper functions that read settings.yaml /
   research.spec.md (``declared_runtime_from_settings``,
   ``declared_output_dir``).
2. Lock in the wizard's branching text — when a runtime / dest is
   inferred, the wizard MUST tell the user what it picked instead of
   asking, AND it must skip the corresponding ``read -r -p`` block.

If anyone later edits ``install.sh`` and drops the helpers or removes
the skip-banner, these tests fire and they have to either restore the
behaviour or update the contract here. Either is fine; silently
reintroducing the redundant question is what we're guarding against.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "dist-templates" / "install.sh"


def _read_install_sh() -> str:
    assert INSTALL_SH.is_file(), INSTALL_SH
    return INSTALL_SH.read_text(encoding="utf-8")


def test_install_sh_defines_runtime_inference_helper() -> None:
    text = _read_install_sh()
    assert "declared_runtime_from_settings()" in text, (
        "install.sh must expose a shell helper that reads settings.yaml's "
        "default_executor.runtime; without it the wizard has no way to "
        "skip the runtime question and the H-runtime-redundant-question "
        "regression resurfaces."
    )
    assert "default_executor" in text, (
        "the runtime helper MUST read default_executor.runtime — that is "
        "the canonical settings.yaml field. Don't fall back to scraping "
        "model names or 'profile' fields; those have unstable shapes."
    )


def test_install_sh_defines_output_dir_inference_helper() -> None:
    text = _read_install_sh()
    assert "declared_output_dir()" in text, (
        "install.sh must expose a shell helper that reads "
        "settings.output_dir AND research.spec.md's location field. "
        "Asking the user for the destination when both encode it is "
        "redundant."
    )
    # Must read BOTH sources (spec OR settings either one is enough)
    assert "output_dir" in text and "location" in text


def test_wizard_skips_runtime_prompt_when_settings_declares_it() -> None:
    """The wizard's generate-block must call the helper BEFORE the prompt
    and must wrap the prompt in a guard that the helper can satisfy.
    """
    text = _read_install_sh()
    # The wizard has TWO runtime questions: one for the vault-spec
    # inline-chat path (a real, unavoidable choice the user must make
    # when both CLIs are installed), and one for the generate step
    # (the redundant one when settings.yaml already declares it).
    # Both contain the literal "Which agent runtime"; the generate-side
    # one is distinguished by "for generation".
    runtime_q_for_generation = "Which agent runtime for generation?"
    assert runtime_q_for_generation in text, (
        "the legacy generate-side prompt line must still exist as fallback "
        "for the both-CLIs-installed-and-no-declared-runtime case"
    )
    skip_banner = "declared in settings.yaml — not asking"
    assert skip_banner in text, (
        "wizard must print a banner explaining that it skipped the runtime "
        "question. Without the banner the user has no signal that their "
        "settings.yaml choice was honoured."
    )
    # Find the actual ``read -r -p`` line (not the comment / docstring
    # mention earlier in the file). The prompt-bearing line is
    # uniquely identified by the literal ``Enter=claude`` hint.
    prompt_pos = text.find(
        "Which agent runtime for generation? [claude/codex] (Enter=claude)"
    )
    assert prompt_pos > 0, "fallback prompt line must still exist verbatim"
    # The helper INVOCATION (a $-substitution) must come before the
    # read line. We look for the unique invocation substring
    # ``$(declared_runtime_from_settings``.
    helper_pos = text.find("$(declared_runtime_from_settings")
    assert 0 <= helper_pos < prompt_pos, (
        f"runtime helper invocation must come before the generate-side "
        f"prompt block so the helper can short-circuit it; "
        f"helper_pos={helper_pos}, prompt_pos={prompt_pos}"
    )


def test_wizard_skips_destination_prompt_when_inferable() -> None:
    text = _read_install_sh()
    # Legacy prompt must still exist as fallback.
    assert "Destination folder:" in text
    # Skip banner specific to destination-folder inference:
    assert "declared in settings.yaml/research.spec.md — not asking" in text
    helper_pos = text.find("$(declared_output_dir")
    prompt_pos = text.find("Destination folder:")
    assert 0 <= helper_pos < prompt_pos, (
        f"output-dir helper must come before the legacy prompt; "
        f"helper_pos={helper_pos}, prompt_pos={prompt_pos}"
    )


def test_runtime_helper_returns_only_known_runtimes() -> None:
    """The helper writes ``claude`` or ``codex`` on stdout — nothing else.

    The wizard's caller branches on this raw value. If the helper ever
    emitted an api / script / friendly-name string the wizard would
    happily try to ``command -v`` it and fail confusingly. Lock the
    safe-list explicitly in the heredoc.
    """
    text = _read_install_sh()
    # The heredoc must check for runtime in ("claude", "codex"). We're
    # loose about whitespace; tight about the safe-list content.
    snippet = re.search(r'runtime\s*in\s*\(\s*"claude"\s*,\s*"codex"\s*\)', text)
    assert snippet is not None, (
        "the runtime helper MUST gate its echo on runtime ∈ {claude, codex}. "
        "Without the safe-list, an unrecognised runtime gets passed to "
        "``command -v`` and produces a nonsense fallback path."
    )
