import textwrap
from pathlib import Path

from research_framework.pipeline.settings import load_vault_settings


def _write(vault: Path, body: str) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "settings.yaml").write_text(textwrap.dedent(body).strip() + "\n")


def test_load_refresh_sources_collectors_from_yaml(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
    pipeline:
      max_cycles: 1
      budget_usd: 1.0
    refresh_sources:
      collectors: [collect_stub.py]
    """,
    )
    s = load_vault_settings(tmp_path)
    assert list(s.refresh_sources.collectors) == ["collect_stub.py"]


def test_refresh_sources_timeout_s_defaults_to_600(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
    pipeline:
      max_cycles: 1
      budget_usd: 1.0
    """,
    )
    assert load_vault_settings(tmp_path).refresh_sources.timeout_s == 600
