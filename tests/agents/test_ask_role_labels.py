"""The `ask` template's Tier-2 labels come from the spec's declared roles (#17).

Principle IX fixes the two-tier *structure*; the label on a Tier-2 entry is
domain vocabulary, so it must be the declared `role` of the matching data
source — never a fixed `[code | intent | domain]` list from software vaults.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.agents import render_agent
from research_framework.spec.parser import parse
from research_framework.spec.schema import DataSourceConfig, SpecConfig

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_FIXED_VOCAB = ("[code | intent | domain]", "`[code]`", "`[intent]`", "`[domain]`")


def _photography_spec() -> SpecConfig:
    """Real example spec whose data sources declare no `role` at all."""
    return parse(_EXAMPLES / "research.spec.md")


def _software_spec() -> SpecConfig:
    spec = _photography_spec()
    spec.data_sources = [
        DataSourceConfig(
            name="Service repos", type="external", role="behaviour", url="github.com"
        ),
        DataSourceConfig(name="Design wiki", type="external", role="intent"),
    ]
    return spec


def _tier2(rendered: str) -> str:
    return rendered.split("Original Sources:", 1)[1].split("## ", 1)[0]


def test_undeclared_roles_render_no_label_and_no_fixed_vocabulary() -> None:
    spec = _photography_spec()
    assert all(not ds.role_declared for ds in spec.data_sources)
    out = render_agent("ask", spec)
    for fixed in _FIXED_VOCAB:
        assert fixed not in out
    assert "Original Sources:" in out and "Vault Sources:" in out
    assert "Photrio" not in _tier2(out)  # no role table when nothing is declared
    assert "declares no `role`" in _tier2(out)


def test_declared_roles_become_the_labels() -> None:
    out = render_agent("ask", _software_spec())
    tier2 = _tier2(out)
    assert "`behaviour`" in tier2 and "Service repos" in tier2
    assert "`intent`" in tier2 and "Design wiki" in tier2
    for fixed in _FIXED_VOCAB:
        assert fixed not in out


def test_free_form_role_is_used_verbatim() -> None:
    spec = _photography_spec()
    spec.data_sources = [
        DataSourceConfig(name="Cookbooks", type="external", role="recipes")
    ]
    out = render_agent("ask", spec)
    assert "`recipes`" in _tier2(out)
    assert "`behaviour`" not in out


def test_dict_data_sources_without_role_get_no_label() -> None:
    """Spec stand-ins (spec-parse.json fallback) carry plain dicts."""
    spec = _photography_spec()
    spec.data_sources = [{"name": "Plain", "type": "external"}]  # type: ignore[list-item]
    assert "Plain" not in _tier2(render_agent("ask", spec))


def test_role_declared_round_trips_through_to_dict() -> None:
    spec = _photography_spec()
    again = SpecConfig.from_dict(spec.to_dict())
    assert all(not ds.role_declared for ds in again.data_sources)
    declared = DataSourceConfig.from_dict(
        {"name": "x", "type": "internal", "role": "intent"}
    )
    assert declared.role_declared
    assert DataSourceConfig.from_dict(declared.to_dict()).role_declared


def _rendered_vault_files(spec: SpecConfig) -> dict[str, str]:
    from research_framework.agents._render import citation_roles
    from research_framework.generator.templates import _env, _templates_src

    env = _env(_templates_src())
    roles = citation_roles(spec)
    return {
        "CLAUDE.md": env.get_template("CLAUDE.md.j2").render(
            spec=spec, citation_roles=roles
        ),
        "vault-config.yaml": env.get_template("vault-config.yaml.j2").render(spec=spec),
        "research": render_agent("research", spec),
    }


def test_no_rendered_vault_file_teaches_the_fixed_vocabulary() -> None:
    for spec in (_photography_spec(), _software_spec()):
        for name, text in _rendered_vault_files(spec).items():
            for fixed in (*_FIXED_VOCAB, "[code]/[intent]/[domain]", "`[vault]`"):
                assert fixed not in text, (name, fixed)


def test_claude_md_citation_section_follows_declared_roles() -> None:
    none = _rendered_vault_files(_photography_spec())["CLAUDE.md"]
    assert "declares no `role`" in none
    some = _rendered_vault_files(_software_spec())["CLAUDE.md"]
    assert "`behaviour` -- Service repos".replace("--", "\u2014") in some
    assert "`intent` -- Design wiki".replace("--", "\u2014") in some
