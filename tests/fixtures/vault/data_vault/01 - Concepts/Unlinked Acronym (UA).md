---
title: Unlinked Acronym (UA)
type: concept
summary: Note with acronym UA appearing unlinked in the body — acronym link failure.
tags: [concept, test-fixture, negative]
source_urls: ["https://example.com/unlinked-acronym"]
related: []
created: 2026-04-16
updated: 2026-04-16
---

# Unlinked Acronym (UA)

## Overview

The title of this note contains the acronym UA inside parentheses. Per vault conventions,
the first occurrence of UA in the body of any note should be wikilinked as [[UA]]. This
fixture intentionally omits that wikilink on the first occurrence (the bare word UA above
this line). That first unlinked UA is the violation to be caught.

## Key Details

Expected validation outcome: `check_acronym_links.py` exits 1 with a message identifying
this file and the acronym UA as unlinked. Subsequent occurrences of UA need not be
wikilinked — only the first. A URL like https://example.com/UA must be ignored. A code
block containing `UA` must also be ignored:

```text
UA appearing in a code block should not be flagged.
```

## Relationships

- Tested by: `tests/scripts/test_check_acronym_links.py::test_unlinked_first_occurrence`
- Negative pair with: [[Valid Concept]]

Extra text to satisfy the 200-word minimum so the word count check passes and the only
violation detected is the unlinked acronym. Words follow: alpha bravo charlie delta echo
foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra
tango uniform victor whiskey xray yankee zulu.
