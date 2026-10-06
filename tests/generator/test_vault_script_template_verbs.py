from jinja2 import Environment, FileSystemLoader, StrictUndefined

from research_framework._assets import asset_path


def _render() -> str:
    env = Environment(
        loader=FileSystemLoader(str(asset_path("templates"))),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    spec = type("S", (), {"name": "Test Vault"})()
    return env.get_template("vault-script.sh.j2").render(
        vault_dir="/vault/abs", spec=spec
    )


def test_vault_script_template_has_refresh_sources_case_arm() -> None:
    out = _render()
    assert "refresh-sources)" in out
    assert "research_framework.cli refresh-sources --vault" in out


def test_vault_script_template_has_regenerate_shim_case_arm() -> None:
    out = _render()
    assert "regenerate-shim)" in out
    assert "research_framework.cli regenerate-shim --vault" in out
