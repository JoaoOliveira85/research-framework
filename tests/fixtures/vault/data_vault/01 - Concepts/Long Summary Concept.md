---
title: Long Summary Concept
type: concept
summary: This summary is intentionally written to exceed the 120 character limit by quite a few characters so that validation fails properly here.
tags: [concept, test-fixture, negative]
source_urls: ["https://example.com/long-summary"]
related: []
created: 2026-04-16
updated: 2026-04-16
---

# Long Summary Concept

## Overview

This note is a negative test fixture. Its frontmatter `summary` field is intentionally
longer than the 120-character limit (this fixture's summary is 140+ chars). Every other
field is valid — only the summary should trigger a validation failure. This isolation is
important so test assertions can verify validate_vault.py catches this specific violation
without also triggering other failures.

## Key Details

Expected validation outcome: exit code 1 with a message naming "summary" as the violating
field and reporting the actual character count exceeds 120. The file path in the violation
report must be this note's absolute path.

## Relationships

- Tested by: `tests/scripts/test_validate_vault.py::test_summary_overflow`
- Negative pair with: [[Valid Concept]]

Extra text to satisfy the 200-word minimum so the word count check passes and the only
violation detected is the summary length. Words follow: alpha bravo charlie delta echo
foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra
tango uniform victor whiskey xray yankee zulu.
