"""URL fetch helper with retry.

Replaces ``fetch_url`` from feeds-vault's collect_rss.py, collect_youtube.py, etc.
"""

import re
import time
import urllib.error
import urllib.request

USER_AGENT = "research-framework-collector/1.0 (educational research; no auth)"
_DEFAULT_TIMEOUT = 30
_DEFAULT_RETRIES = 3
_RETRY_BACKOFF = 2.0
# A feed or an article page is kilobytes; a long feed a few megabytes. The cap
# sits far above both and only keeps a misbehaving server from streaming an
# unbounded body into memory.
_MAX_BODY_BYTES = 32 * 1024 * 1024

# ``<?xml version="1.0" encoding="ISO-8859-1"?>`` — an XML document (every
# feed) names its own encoding at its very start.
_XML_PROLOG = "<?xml"
_XML_PROLOG_ENCODING = re.compile(
    rb"""<\?xml[^>]*?\sencoding\s*=\s*["']([A-Za-z][A-Za-z0-9._-]*)["']"""
)


def _decode(raw: bytes, header_charset: str | None) -> str:
    """Decode a response body to text.

    The HTTP charset comes first, then the encoding the document declares in
    its XML prolog, then UTF-8; the first that decodes wins. ElementTree
    ignores the prolog of a document handed to it as ``str``, so a feed
    decoded wrongly here stays wrong.
    """
    if header_charset:
        try:
            return raw.decode(header_charset)
        except (UnicodeDecodeError, LookupError):
            pass
    declared = _XML_PROLOG_ENCODING.match(raw[:256])
    if declared:
        try:
            text = raw.decode(declared.group(1).decode("ascii"))
        except (UnicodeDecodeError, LookupError):
            text = ""
        # The prolog was readable as ASCII, so the real encoding keeps ASCII
        # as it is: a declaration that does not (``utf-16`` written by a
        # serializer onto UTF-8 bytes) is not the encoding of these bytes.
        if text.startswith(_XML_PROLOG):
            return text
    return raw.decode("utf-8", errors="replace")


class ResponseTooLarge(urllib.error.URLError):
    """The body ran past :data:`_MAX_BODY_BYTES`: a failed fetch, not retried."""


def get(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    retries: int = _DEFAULT_RETRIES,
) -> tuple[str, int]:
    """Fetch *url* and return ``(text, http_status_code)``.

    Retries on connection-level failures (``urllib.error.URLError``) up to
    *retries* times with exponential back-off.  HTTP errors (4xx/5xx) are not
    retried — the caller decides whether to skip or abort.

    Raises:
        urllib.error.HTTPError: on non-2xx responses that urllib raises.
        ResponseTooLarge: a ``URLError`` for a body over the size cap.
        urllib.error.URLError: if all retry attempts fail.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read(_MAX_BODY_BYTES + 1)
                if len(raw) > _MAX_BODY_BYTES:
                    raise ResponseTooLarge(
                        f"response body over {_MAX_BODY_BYTES} bytes"
                    )
                return _decode(raw, resp.headers.get_content_charset()), resp.status
        except (urllib.error.HTTPError, ResponseTooLarge):
            # HTTP errors and oversize bodies are not retried
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
    assert last_exc is not None
    raise last_exc
