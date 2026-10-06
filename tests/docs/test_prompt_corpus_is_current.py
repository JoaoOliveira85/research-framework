"""Prompt-corpus drift guard (issue #280).

`docs/prompts/` reproduces every prompt the framework puts in front of a
model. A copy of a prompt is worth nothing if it can silently stop matching
the prompt — a stale reproduction is worse than none, because a clean-room
reader has no way to tell. This guard is what makes the corpus load-bearing:
it re-derives every generated file from its source and fails on any
difference, so the only way to change a prompt is to change the source and
re-run the renderer.

It also fails on a prompt-shaped file the renderer has not been told about.
That is the anti-fail-open half: a guard that only checks the files it
already knows would pass forever after someone adds the twelfth template and
forgets the corpus.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.render_prompt_corpus import (
    MANIFEST,
    NOT_A_PROMPT,
    OUTPUT_DIR,
    REPO_ROOT,
    all_prompts,
    drifted,
    render_one,
    skill_prompts,
    source_digest,
    unclassified_sources,
)


def test_every_prompt_source_exists() -> None:
    """A renamed or deleted prompt must break here, not silently leave a
    stale copy behind."""
    missing = [p.source for p in all_prompts() if not (REPO_ROOT / p.source).is_file()]
    assert not missing, "declared prompt sources that do not exist:\n" + "\n".join(
        f"  - {source}" for source in missing
    )


def test_no_prompt_shaped_file_is_unclassified() -> None:
    """Every file under the discovery globs is rendered, recorded, or
    excused with a reason. Nothing is allowed to be none of the three."""
    unclassified = unclassified_sources()
    assert not unclassified, (
        "prompt-shaped file(s) the corpus does not classify — add each to "
        "_TEMPLATES, to the skills root, or to NOT_A_PROMPT with a reason:\n"
        + "\n".join(f"  - {source}" for source in unclassified)
    )


def test_the_corpus_is_current() -> None:
    problems = drifted()
    assert not problems, (
        "docs/prompts/ has drifted from its sources. Run "
        "`python scripts/render_prompt_corpus.py`:\n"
        + "\n".join(f"  - {problem}" for problem in problems)
    )


def test_check_mode_agrees_with_the_committed_tree() -> None:
    """The script's own `--check` is what CONTRIBUTING and the guard battery
    invoke; run it end to end rather than trusting the in-process helper."""
    result = subprocess.run(
        [sys.executable, "scripts/render_prompt_corpus.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"`render_prompt_corpus.py --check` exited {result.returncode}\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_a_rendered_copy_reproduces_its_source_verbatim() -> None:
    """The whole point: the body between the fences is the source's bytes,
    not a paraphrase and not a re-wrap."""
    problems: list[str] = []
    for prompt in all_prompts():
        if not prompt.is_rendered:
            continue
        assert prompt.slug is not None
        source_text = (REPO_ROOT / prompt.source).read_text(encoding="utf-8")
        rendered = (OUTPUT_DIR / f"{prompt.slug}.md").read_text(encoding="utf-8")
        for line in source_text.splitlines():
            if line and line not in rendered:
                problems.append(f"{prompt.slug}: source line missing — {line[:60]!r}")
                break
    assert not problems, "rendered copies that are not verbatim:\n" + "\n".join(
        f"  - {p}" for p in problems
    )


def test_a_hand_edited_copy_is_detected() -> None:
    """Proves the guard can fail. Without this, a renderer bug that made
    every comparison vacuous would look exactly like a clean corpus."""
    prompt = next(p for p in all_prompts() if p.is_rendered)
    assert prompt.slug is not None
    target = OUTPUT_DIR / f"{prompt.slug}.md"
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(original + "\nhand-edited\n", encoding="utf-8")
        assert any(prompt.slug in problem for problem in drifted())
    finally:
        target.write_text(original, encoding="utf-8")


def test_an_orphaned_copy_is_detected() -> None:
    """A prompt removed from the sources must not leave its reproduction
    behind to be read as current."""
    stray = OUTPUT_DIR / "not-a-prompt-any-more.md"
    try:
        stray.write_text("# stale\n", encoding="utf-8")
        assert any("orphaned" in problem for problem in drifted())
    finally:
        stray.unlink(missing_ok=True)


def test_the_manifest_records_every_prompt() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    missing = [p.source for p in all_prompts() if f"`{p.source}`" not in text]
    assert not missing, "prompts absent from the manifest:\n" + "\n".join(
        f"  - {source}" for source in missing
    )


def test_the_manifest_hashes_match_the_sources() -> None:
    """The recorded-not-copied half is only an index if the hash is real."""
    text = MANIFEST.read_text(encoding="utf-8")
    stale = [p.source for p in all_prompts() if f"`{source_digest(p)}`" not in text]
    assert not stale, "manifest hashes that do not match their source:\n" + "\n".join(
        f"  - {source}" for source in stale
    )


def test_the_skill_corpus_is_not_empty() -> None:
    """Keeps the recorded-not-copied branch honest: an empty skills root
    would make that whole table a claim about nothing."""
    skills = skill_prompts()
    assert len(skills) >= 20, f"expected the 26-file skill corpus, found {len(skills)}"


def test_every_exclusion_names_a_real_file_and_a_reason() -> None:
    problems = []
    for source, reason in NOT_A_PROMPT.items():
        if not (REPO_ROOT / source).is_file():
            problems.append(f"{source}: no such file — drop the exclusion")
        if not reason.strip():
            problems.append(f"{source}: excluded with no reason")
    assert not problems, "\n".join(f"  - {p}" for p in problems)


def test_a_fenced_source_is_still_reproducible() -> None:
    """Several prompts contain triple-backtick blocks; the wrapper fence has
    to be longer than anything inside, or the reproduction is truncated at
    the first inner fence."""
    for prompt in all_prompts():
        if not prompt.is_rendered:
            continue
        source_text = (REPO_ROOT / prompt.source).read_text(encoding="utf-8")
        if "```" not in source_text:
            continue
        rendered = render_one(prompt)
        opening = rendered.split("\n")[-2] if rendered.endswith("\n") else ""
        assert opening.startswith("```"), f"{prompt.slug}: no closing fence"
        assert len(opening) > 3, (
            f"{prompt.slug}: wrapper fence is 3 backticks but the source "
            "contains a fence — the reproduction would truncate"
        )


def test_the_output_directory_holds_only_generated_files() -> None:
    """Someone hand-writing a note into docs/prompts/ would be writing it
    into a directory the renderer owns and will not preserve."""
    unexpected = [
        path.name
        for path in sorted(OUTPUT_DIR.iterdir())
        if path.is_file() and path.suffix != ".md"
    ]
    assert not unexpected, f"non-generated files in docs/prompts/: {unexpected}"


def test_generated_files_say_they_are_generated() -> None:
    for path in sorted(OUTPUT_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert "GENERATED by scripts/render_prompt_corpus.py" in text, (
            f"{path.name} does not warn a reader that editing it is pointless"
        )


def test_the_repo_root_resolves_to_this_checkout() -> None:
    """Cheap sanity check: the module walks up two parents to find the repo,
    and a moved file would silently point the whole guard elsewhere."""
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert Path(OUTPUT_DIR).is_relative_to(REPO_ROOT)
