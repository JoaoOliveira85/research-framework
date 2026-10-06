---
title: Broken Wikilink
type: concept
summary: Note whose related field contains a wikilink to a non-existent note.
tags: [concept, test-fixture, negative]
source_urls: ["https://example.com/broken-wikilink"]
related: ["Nonexistent Target"]
created: 2026-04-16
updated: 2026-04-16
---

# Broken Wikilink

## Overview

This note has a `related` field referencing a note title that does not exist in the
vault. Every other field is valid — only the unresolved wikilink should trigger a
validation failure.

## Key Details

Expected validation outcome: `validate_vault.py` exits 1 with a message identifying this
file and the unresolved wikilink target "Nonexistent Target". The reported field should
be "related".

## Relationships

- Tested by: `tests/scripts/test_validate_vault.py::test_broken_wikilink`
- Negative pair with: [[Valid Concept]]

Extra text to satisfy the 200-word minimum so the word count check passes and the only
violation detected is the broken wikilink. Words follow: alpha bravo charlie delta echo
foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra
tango uniform victor whiskey xray yankee zulu. More filler to reach the threshold and
ensure no additional validators trigger on this note beyond the expected one.
