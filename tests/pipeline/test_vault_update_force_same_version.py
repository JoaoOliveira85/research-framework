"""`./vault update --force` must re-install a same-version bundle.

Surfaced 2026-08-27 while validating an unreleased branch across five live
vaults. `--force` only ever bypassed the dirty-working-tree guard; the version
short-circuit ran earlier and had no force path, so when the archive's version
string equalled the vault's, `decide()` returned `noop` and the vault-local
`scripts/` and `_templates/` were never re-copied — even though the Python
package installed in the venv was completely different code. The verb reported
exit 0 and changed nothing, which is the worst possible combination: an
operator testing a build has no signal that the bundle is stale.

Defensible for released versions (a bump should accompany code changes), but it
makes an unreleased build untestable through the supported verb — exactly when
an operator most needs it.
"""

from __future__ import annotations

import pytest

from research_framework.pipeline.vault_update import decide


def test_same_version_is_a_noop_without_force() -> None:
    """Unchanged default: no version change, no work."""
    d = decide("1.0.0rc11", "1.0.0rc11")
    assert d.action == "noop"
    assert d.exit_code == 0


def test_same_version_proceeds_with_force() -> None:
    """The regression this test exists for."""
    d = decide("1.0.0rc11", "1.0.0rc11", force=True)
    assert d.action == "proceed"
    assert d.exit_code == 0
    assert "force" in d.message.lower()


def test_upgrade_is_unaffected_by_force() -> None:
    for force in (False, True):
        d = decide("1.0.0rc10", "1.0.0rc11", force=force)
        assert d.action == "proceed", force


def test_force_does_not_wave_through_an_unconfirmed_downgrade() -> None:
    """--force is about re-installing, not about overriding the 012 guard."""
    d = decide("1.0.0rc11", "1.0.0rc10", force=True)
    assert d.action == "refuse"
    assert d.exit_code == 2


def test_confirmed_pinned_downgrade_still_proceeds() -> None:
    d = decide("1.0.0rc11", "1.0.0rc10", pinned_ref="v1.0.0rc10", confirmed=True)
    assert d.action == "proceed"


@pytest.mark.parametrize("force", [False, True])
def test_message_always_names_the_target(force: bool) -> None:
    d = decide("1.0.0rc11", "1.0.0rc11", force=force)
    assert "1.0.0rc11" in d.message
