"""Tests for scripts/raw_capture.py — the raw_data/ sidecar capture helper.

Network-dependent paths are stubbed via monkeypatch so tests run offline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "raw_capture.py"


def _load():
    spec = importlib.util.spec_from_file_location("raw_capture", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["raw_capture"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rc():
    return _load()


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, *_args):
        return self._body


class TestExtractHtmlTitle:
    """rc5 reference-vault finding: captured ``<title>`` strings with ``::`` / ``": "``
    separators (Spring docs: ``Exceptions :: Spring Framework``) were copied
    verbatim into ``source_urls[].title`` and broke note frontmatter with
    "mapping values are not allowed here". The extractor now sanitizes them."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                "<title>Exceptions :: Spring Framework</title>",
                "Exceptions - Spring Framework",
            ),
            ("<title>JMX :: Spring Framework</title>", "JMX - Spring Framework"),
            ("<title>Guide: Getting Started</title>", "Guide - Getting Started"),
            # Colon NOT followed by whitespace is YAML-safe — leave it alone.
            ("<title>Release 10:30 build</title>", "Release 10:30 build"),
            ("<title>Plain Title</title>", "Plain Title"),
        ],
    )
    def test_sanitizes_yaml_hostile_colons(self, rc, raw: str, expected: str) -> None:
        assert rc._extract_html_title(raw) == expected

    def test_extracted_title_is_yaml_safe(self, rc) -> None:
        import yaml

        title = rc._extract_html_title("<title>Exceptions :: Spring Framework</title>")
        # The whole point: an UNQUOTED frontmatter scalar must now parse.
        parsed = yaml.safe_load(f"title: {title}\n")
        assert parsed == {"title": "Exceptions - Spring Framework"}


class TestCapture:
    def test_capture_writes_payload_and_meta(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_root = tmp_path / "raw_data"
        html = b"<html><head><title>Hello</title></head><body>ok</body></html>"
        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(html, "text/html"),
        )

        payload, meta = rc.capture(
            "https://example.invalid/page", raw_root, source_type="article"
        )
        assert payload.exists()
        assert payload.suffix == ".html"
        assert payload.read_bytes() == html

        # meta.json sibling
        meta_file = payload.with_suffix("").parent / (payload.stem + ".meta.json")
        assert meta_file.exists()
        on_disk = json.loads(meta_file.read_text())
        assert on_disk["url"] == "https://example.invalid/page"
        assert on_disk["source_type"] == "article"
        assert on_disk["title"] == "Hello"
        assert on_disk["filename"] == payload.name

    def test_capture_is_idempotent(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_root = tmp_path / "raw_data"
        calls = {"n": 0}

        def fake_urlopen(*a, **kw):
            calls["n"] += 1
            return _FakeResponse(b"hello", "text/plain")

        monkeypatch.setattr(rc.urllib.request, "urlopen", fake_urlopen)

        rc.capture("https://example.invalid/x", raw_root)
        rc.capture("https://example.invalid/x", raw_root)
        # Second call re-uses the stored meta.json instead of fetching again.
        assert calls["n"] == 1

    def test_capture_refuses_non_http_url(self, tmp_path: Path, rc) -> None:
        """The http(s) guard lived only in ``main``; ``raw_capture_batch`` calls
        ``capture()`` directly with URLs read from agent-written notes, and
        ``urlopen`` reads ``file://`` URLs off local disk into ``raw_data/``."""
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET", encoding="utf-8")
        raw_root = tmp_path / "raw_data"

        with pytest.raises(ValueError, match="http"):
            rc.capture(secret.as_uri(), raw_root)

        assert not raw_root.exists() or not any(raw_root.rglob("*.*"))

    def test_capture_returns_none_on_network_error(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*a, **kw):
            raise URLError("unreachable")

        monkeypatch.setattr(rc.urllib.request, "urlopen", boom)
        assert rc.capture("https://example.invalid/x", tmp_path / "raw_data") is None

    def test_capture_honours_size_cap(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        big = b"x" * (rc._MAX_BYTES + 100)
        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(big, "application/octet-stream"),
        )
        payload, meta = rc.capture("https://example.invalid/big", tmp_path / "raw_data")
        assert meta["bytes"] == rc._MAX_BYTES
        assert payload.stat().st_size == rc._MAX_BYTES


class TestPickExtension:
    @pytest.mark.parametrize(
        "ct,url,expected",
        [
            ("text/html", "https://x/", "html"),
            ("application/pdf", "https://x/doc", "pdf"),
            ("text/plain; charset=utf-8", "https://x/a", "txt"),
            ("", "https://x/paper.pdf", "pdf"),
            ("application/octet-stream", "https://x/no-ext", "bin"),
        ],
    )
    def test_pick_extension(self, rc, ct: str, url: str, expected: str) -> None:
        assert rc._pick_extension(ct, url) == expected


class TestClassifyPayload:
    """Spec 050 / post-mortem 2026-05-30: detect JS-shell captures so codex
    gets an actionable signal instead of spinning on unscrapable URLs."""

    # Real-world bytes captured from mistral.ai during the feeds-vault cycle
    # 003 incident — verbatim, no editing. If this fixture stops parsing
    # as a js_shell, the classifier has regressed and we'll re-introduce
    # the post-mortem hang.
    _MISTRAL_VIBE_SHELL = (
        b"<!doctype html>\n"
        b'<html lang="en">\n'
        b"  <head>\n"
        b'    <meta charset="UTF-8" />\n'
        b'    <meta name="viewport" content="width=device-width, '
        b'initial-scale=1.0" />\n'
        b'    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />\n'
        b'    <meta name="robots" content="noindex,nofollow" />\n'
        b'    <script type="module" crossorigin '
        b'src="/assets/index-Djke727L.js"></script>\n'
        b'    <link rel="stylesheet" crossorigin '
        b'href="/assets/index-DJaKAgAD.css">\n'
        b"  </head>\n"
        b'  <body class="min-h-dvh font-body">\n'
        b'    <div id="root"></div>\n'
        b"    <script>window.global = window;</script>\n"
        b"  </body>\n"
        b"</html>\n"
    )

    def test_real_mistral_shell_classifies_as_js_shell(self, rc):
        assert rc.classify_payload(self._MISTRAL_VIBE_SHELL, "text/html") == "js_shell"

    def test_rich_html_with_article_text_classifies_as_rich(self, rc):
        html = (
            b"<!doctype html><html><head><title>Article</title></head>"
            b"<body><h1>The big news</h1>"
            + b"<p>Lorem ipsum dolor. " * 80
            + b"</p></body></html>"
        )
        assert rc.classify_payload(html, "text/html") == "rich"

    def test_thin_html_classifies_as_thin(self, rc):
        # Real content but very short — bumper-sticker page.
        html = b"<html><body><p>Hi.</p></body></html>"
        assert rc.classify_payload(html, "text/html") == "thin"

    def test_pdf_classifies_as_binary(self, rc):
        # PDF magic header — should never be js_shell regardless of size.
        assert rc.classify_payload(b"%PDF-1.7\n...", "application/pdf") == "binary"

    def test_next_js_shell_signature_is_detected(self, rc):
        html = (
            b"<!doctype html><html><body>"
            b'<div id="__next"></div>'
            b'<script src="/_next/main.js"></script>'
            b"</body></html>"
        )
        assert rc.classify_payload(html, "text/html") == "js_shell"

    def test_empty_root_without_script_is_thin_not_shell(self, rc):
        """``<div id="root"></div>`` alone isn't enough — the SPA
        signature requires a script tag too, otherwise we'd flag
        legitimate placeholder pages as JS shells."""
        html = b'<html><body><div id="root"></div></body></html>'
        assert rc.classify_payload(html, "text/html") in ("thin", "rich")

    def test_capture_records_payload_kind_in_meta(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        raw_root = tmp_path / "raw_data"
        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(self._MISTRAL_VIBE_SHELL, "text/html"),
        )
        _, meta = rc.capture("https://mistral.ai/vibe", raw_root)
        assert meta["payload_kind"] == "js_shell"

    def test_cli_emits_js_shell_status_word(
        self,
        tmp_path: Path,
        rc,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The CLI must print JS_SHELL (not OK) when the capture is a
        JavaScript-only shell. The status word is grepable and the LLM's
        tool-output reader can branch on it."""
        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(self._MISTRAL_VIBE_SHELL, "text/html"),
        )
        rc.main(
            [
                "https://mistral.ai/vibe",
                "--vault",
                str(tmp_path),
            ]
        )
        out = capsys.readouterr()
        assert out.out.splitlines()[0].startswith("JS_SHELL"), (
            f"first line was: {out.out.splitlines()[0]!r}"
        )
        assert "payload_kind=js_shell" in out.out
        # The stderr warning is what makes the situation actionable for
        # an LLM reading the tool output.
        assert "JavaScript-only SPA shell" in out.err

    def test_cli_emits_ok_for_rich_capture(
        self,
        tmp_path: Path,
        rc,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rich = (
            b"<!doctype html><html><head><title>Real article</title></head>"
            b"<body>" + b"<p>Real prose content. " * 60 + b"</p></body></html>"
        )
        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(rich, "text/html"),
        )
        rc.main(
            [
                "https://example.invalid/real",
                "--vault",
                str(tmp_path),
            ]
        )
        out = capsys.readouterr()
        assert out.out.splitlines()[0].startswith("OK"), out.out.splitlines()[0]
        assert "payload_kind=rich" in out.out
        assert out.err == ""


class TestVaultHealthIntegration:
    """End-to-end: capture writes a mirror that vault_health finds."""

    def test_vault_health_picks_up_raw_capture_output(
        self, tmp_path: Path, rc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange: minimal vault + mirror via raw_capture().
        vault = tmp_path / "vault"
        (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)
        (vault / "_templates").mkdir()
        (vault / "_pipeline").mkdir()
        raw_root = vault / "raw_data"

        monkeypatch.setattr(
            rc.urllib.request,
            "urlopen",
            lambda *a, **kw: _FakeResponse(b"<html/>", "text/html"),
        )
        rc.capture("https://example.invalid/page", raw_root)

        # Act: load vault_health and ask for the mirror. (module must be in
        # sys.modules before exec so @dataclass can resolve the enclosing
        # module — otherwise dataclasses raises AttributeError on NoneType.)
        spec = importlib.util.spec_from_file_location(
            "vh_module", SCRIPT_PATH.parent / "vault_health.py"
        )
        vh = importlib.util.module_from_spec(spec)
        sys.modules["vh_module"] = vh
        spec.loader.exec_module(vh)

        mirror = vh._raw_data_mirror(vault, "https://example.invalid/page")

        # Assert: mirror matches the captured payload.
        assert mirror is not None
        assert mirror.exists()
        assert mirror.suffix == ".html"
