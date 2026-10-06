---
title: Missing Source
type: concept
summary: A concept note missing the source_urls field entirely — negative test fixture.
tags: [concept, test-fixture, negative]
source_urls: []
related: []
created: 2026-04-16
updated: 2026-04-16
---

# Missing Source

## Overview

This note is a negative test fixture. Its `source_urls` frontmatter field is an empty
list. Every other field is valid. Only the missing source should trigger a validation
failure.

## Key Details

Expected validation outcome: exit code 1 with a message naming "source_urls" as the
violating field. The violation report must specify that at least one source URL is
required and the current list is empty.

## Relationships

- Tested by: `tests/scripts/test_validate_vault.py::test_missing_source_urls`
- Negative pair with: [[Valid Concept]]

Extra text to satisfy the 200-word minimum so the word count check passes and the only
violation detected is the missing source. Words follow: alpha bravo charlie delta echo
foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra
tango uniform victor whiskey xray yankee zulu. More filler to reach the threshold and
ensure no additional validators trigger on this note beyond the expected one.
