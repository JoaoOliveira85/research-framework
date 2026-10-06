from pathlib import Path

from research_framework.pipeline.scaffold_baseline import read_vault_baseline
from research_framework.pipeline.scaffold_models import ManifestEntry, ScaffoldManifest


def test_baseline_does_not_walk_data_vault(tmp_path: Path):
    vault = tmp_path / "v"
    (vault / "data_vault" / "deep" / "nested").mkdir(parents=True)
    (vault / "data_vault" / "deep" / "nested" / "user_note.md").write_text(
        "user content"
    )
    (vault / "data_vault" / "AGENTS.md").write_text("user")
    (vault / "_pipeline").mkdir()
    (vault / "CLAUDE.md").write_text("hi")

    manifest = ScaffoldManifest(
        framework_version=1,
        generator_commit="x",
        generated_at="t",
        entries=(
            ManifestEntry(
                path="CLAUDE.md",
                kind="markdown",
                template_version=1,
                rendered_sha256="abc",
                is_user_owned_after_first_write=False,
            ),
        ),
    )

    bl = read_vault_baseline(vault, manifest)
    assert set(bl.files.keys()) == {"CLAUDE.md"}
