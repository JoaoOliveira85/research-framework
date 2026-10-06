# Contract: Source Attribution & Incidents (029)

Defines the three behavioural contracts the implementation + tests pin: `normalize_source_url()`,
the `_note_cites_source` predicate, and the `source-incidents.md` line grammar.

## 1. `normalize_source_url(url: str) -> str`

Stdlib `urllib.parse` only. Canonicalizes for **matching** (not for storage/display).

Rules: lowercase scheme + host · strip a single trailing `/` from path · drop `#fragment` ·
**preserve query string** · leave userinfo/port as-is · non-URL input returned stripped+lowercased.

| Input | Output | Note |
|---|---|---|
| `https://Example.com/Feed/` | `https://example.com/Feed` | host lowercased, trailing slash dropped, **path case preserved** |
| `http://example.com/a#section` | `http://example.com/a` | fragment dropped |
| `https://learning.oreilly.com/search/?q=rust` | `https://learning.oreilly.com/search?q=rust` | **query preserved** (load-bearing) |
| `https://youtube.com/watch?v=abc#t=10` | `https://youtube.com/watch?v=abc` | query kept, fragment dropped |
| `https://example.com` | `https://example.com` | no path → unchanged |
| `Anthropic` (bare name) | `anthropic` | non-URL → lowercased/stripped (lets name fallback work uniformly) |
| `""` / `None` | `""` | empty-safe |

**MUST NOT**: sort/dedupe query params; strip query; resolve redirects; hit the network.

## 2. `_note_cites_source(frontmatter: dict, source_name: str, source_url: str) -> bool`

Single predicate shared by `record_cycle` (per-cycle, over `notes_created`) and
`_count_notes_referencing` (all-time, over `data_vault/`). Q3 = normalized-URL **OR** name fallback.

```
sources = frontmatter.get("source_urls") or []
if not isinstance(sources, list): sources = [sources]          # coerce scalar → 1-elem
n_url = normalize_source_url(source_url)
for entry in sources:
    if entry is None: continue                                  # skip malformed entry (debug log)
    n_entry = normalize_source_url(str(entry))
    if n_url and n_url in n_entry:        return True           # normalized-URL match (substring)
    if source_name and source_name in str(entry):  return True  # name fallback (raw substring)
return False
```

| Case | `source_urls` frontmatter | name / url | Result |
|---|---|---|---|
| exact URL | `["https://example.com/feed"]` | url=`https://example.com/feed/` | ✅ (normalized) |
| fragment differs | `["https://x.io/a#intro"]` | url=`https://x.io/a` | ✅ |
| query differs | `["…/search?q=go"]` | url=`…/search?q=rust` | ❌ (query is load-bearing) |
| name-only citation | `["Anthropic blog"]` | name=`Anthropic` | ✅ (fallback) |
| scalar (non-list) | `"https://example.com/feed"` | url=`…/feed` | ✅ (coerced) |
| missing field | `{}` (no `source_urls`) | any | ❌ (placeholder note; not counted) |
| malformed entry | `[None, 123]` | name=`X` | per-entry skip; `123`→`"123"` name-substring tested |

**MUST NOT** raise on malformed frontmatter — skip the entry, never the cycle (Edge Cases).

## 3. `source-incidents.md` line grammar (append-only — FR-007 / Q2)

```
# Source incidents
<blank>
- <ISO8601-Z> — `<name>` degraded: <one-line reason>
- <ISO8601-Z> — `<name>` resolved
```

- File created with the `# Source incidents\n\n` header on first write (existing `mark_degraded`).
- Every detection appends a `degraded` line; every recovery appends a `resolved` line. **No line is
  ever deleted or rewritten.** Current state of a source = its most recent line.
- `<reason>` is whitespace-collapsed (existing `mark_degraded`: `" ".join(reason.split())`).
- Timestamp: `datetime.now(UTC).isoformat(timespec="seconds")` with `+00:00`→`Z`.

## 4. Relationship to the JSON sidecar (FR-001a)

`cycle-NNN-source-incidents.json` (written by `notify_required_source_degraded`, **unchanged**)
is the per-cycle machine record (`{"count": N, ...}`) used for the abort-threshold decision.
`source-incidents.md` is the cumulative human log. The two are independent surfaces; a test MUST
assert **both** are written on a required-source degradation.
