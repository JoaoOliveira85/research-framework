#!/usr/bin/env python3
"""YouTube module extractor — stdin/stdout JSON contract (spec 020).

Lifecycle:
1. Read JSON request from stdin.
2. Resolve the YouTube video id from ``source.url`` (accepting both
   ``youtube.com/watch?v=...`` and ``youtu.be/...`` shapes).
3. Shell out to ``yt-dlp`` (path overridable via ``YT_DLP_BIN`` for
   tests) to fetch metadata and — when the ``YT_SKIP_SUBS`` env is
   unset — subtitles.
4. Emit a ``SignalPayload`` JSON on stdout. The envelope honours
   ``signal-payload.schema.json``; ``facts`` is intentionally empty
   in this v0.1.0 — LLM-driven facts extraction is the obvious
   follow-up.

Error policy (D9, spec 020):
- Missing ``yt-dlp`` binary → ``verdict=error``, ``partial=false``,
  empty facts (clean envelope, parent handles retries).
- Missing / non-YouTube ``source.url`` → ``verdict=error``.
- yt-dlp returned no subtitles → ``verdict=empty`` (still a valid
  envelope; the framework will treat as "nothing to extract this
  cycle"). The transcript hash falls back to the video id so the
  cache key stays stable.

The module never holds global state and never imports framework
code (Principle V: subprocess isolation). The only framework
contract surfaces are stdin (request) and stdout (SignalPayload).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Neutral placeholder — the framework overwrites this with the runtime
# bridge_version after parsing (see
# `src/research_framework/pipeline/source_bridge/extractor.py::invoke_extractor`).
# Mirrors the `code` module's convention to avoid per-release drift in the
# shipped module assets.
BRIDGE_VERSION = "0.0.0"
YT_DLP_DEFAULT = "yt-dlp"

_VIDEO_ID_RX = re.compile(
    r"^https?://(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]+)"
    r"|^https?://youtu\.be/([A-Za-z0-9_-]+)"
)


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _yt_dlp_bin() -> str:
    return os.environ.get("YT_DLP_BIN", YT_DLP_DEFAULT)


def _video_id_from_url(url: str) -> str | None:
    match = _VIDEO_ID_RX.match(url)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "youtube",
        "source_id": source_id or "unknown",
        "source_version": "unknown",
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "error",
        "truncated": False,
        "partial": False,
        "facts": {},
        "notable": [
            {
                "observation": reason,
                "confidence": "high",
                "evidence_ref": "extractor:precondition",
            }
        ],
    }


def _fetch_metadata(video_id: str) -> dict[str, Any] | None:
    """Run ``yt-dlp --dump-json`` for the video. Returns parsed JSON or None."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        proc = subprocess.run(
            [
                _yt_dlp_bin(),
                "--dump-json",
                "--no-playlist",
                "--quiet",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return info if isinstance(info, dict) else None


def _fetch_subtitles(video_id: str) -> str | None:
    """Run yt-dlp to grab manual-then-auto subtitles. Returns SRT text."""
    if os.environ.get("YT_SKIP_SUBS"):
        return None
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="yt-subs-") as tmp:
        tmp_path = Path(tmp)
        for flag in ("--write-subs", "--write-auto-subs"):
            try:
                subprocess.run(
                    [
                        _yt_dlp_bin(),
                        "--skip-download",
                        flag,
                        "--sub-langs",
                        "en.*",
                        "--convert-subs",
                        "srt",
                        "--no-playlist",
                        "--quiet",
                        "-o",
                        str(tmp_path / f"{video_id}.%(ext)s"),
                        url,
                    ],
                    capture_output=True,
                    timeout=90,
                    check=False,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            for srt in sorted(tmp_path.glob(f"{video_id}*.srt")):
                return srt.read_text(encoding="utf-8", errors="replace")
    return None


def _srt_to_text(srt: str) -> str:
    """Strip SRT formatting to plain readable text (de-duped lines)."""
    lines: list[str] = []
    for line in srt.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+$", stripped):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", stripped):
            continue
        no_tags = re.sub(r"<[^>]+>", "", stripped)
        if no_tags:
            lines.append(no_tags)
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)


def _transcript_version(video_id: str, transcript: str | None) -> str:
    """Stable cache key — hash of transcript text (or fallback to video id)."""
    if not transcript:
        return f"no-transcript:{video_id}"
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    url = str(source.get("url", ""))
    video_id = _video_id_from_url(url) if url else None
    if not video_id:
        return {"source_version": "unknown"}
    transcript_srt = _fetch_subtitles(video_id)
    transcript_text = _srt_to_text(transcript_srt) if transcript_srt else None
    return {"source_version": _transcript_version(video_id, transcript_text)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")

    video_id = _video_id_from_url(url)
    if not video_id:
        return _error_payload(source_id, "url is not a recognised YouTube URL")

    metadata = _fetch_metadata(video_id)
    if metadata is None:
        return _error_payload(
            source_id, "yt-dlp metadata fetch failed (binary missing or network error)"
        )

    transcript_srt = _fetch_subtitles(video_id)
    transcript_text = _srt_to_text(transcript_srt) if transcript_srt else None
    has_transcript = bool(transcript_text)

    title = str(metadata.get("title") or "")
    uploader = str(metadata.get("uploader") or metadata.get("channel") or "")
    upload_date = str(metadata.get("upload_date") or "")
    formatted_date = (
        f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        if len(upload_date) == 8 and upload_date.isdigit()
        else ""
    )

    notable: list[dict[str, Any]] = []
    if title:
        notable.append(
            {
                "observation": f"YouTube video title: {title}",
                "confidence": "high",
                "evidence_ref": f"video:{video_id}",
            }
        )
    if uploader:
        notable.append(
            {
                "observation": f"Uploaded by {uploader}",
                "confidence": "high",
                "evidence_ref": f"video:{video_id}",
            }
        )
    if formatted_date:
        notable.append(
            {
                "observation": f"Upload date {formatted_date}",
                "confidence": "high",
                "evidence_ref": f"video:{video_id}",
            }
        )

    return {
        "module": "youtube",
        "source_id": source_id,
        "source_version": _transcript_version(video_id, transcript_text),
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "ok" if has_transcript else "empty",
        "truncated": False,
        "partial": False,
        # v0.1.0 ships the envelope only; downstream LLM extraction
        # against the per-vault FactsSchema fills these buckets.
        "facts": {},
        "notable": notable,
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "extract"
    payload = _read_stdin()
    if command == "get_source_version":
        out = cmd_get_source_version(payload)
    else:
        out = cmd_extract(payload)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
