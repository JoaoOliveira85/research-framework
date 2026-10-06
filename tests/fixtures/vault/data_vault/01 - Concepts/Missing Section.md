---
title: Missing Section
type: concept
summary: A concept note missing the Relationships section — template compliance failure.
tags: [concept, test-fixture, negative]
source_urls: ["https://example.com/missing-section"]
related: []
created: 2026-04-16
updated: 2026-04-16
---

# Missing Section

## Overview

This note has valid frontmatter but is missing the required `## Relationships` section
that the concept template defines. Every other aspect is valid — the only failure mode
is template compliance.

## Key Details

Expected validation outcome: `check_template_compliance.py` exits 1 with a message
naming "Relationships" as the missing section. `validate_vault.py` should not flag this
note (frontmatter is valid) — the failure is purely structural.

Extra text to satisfy the 200-word minimum so the word count check passes and the only
violation detected is the missing section. Words follow: alpha bravo charlie delta echo
foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra
tango uniform victor whiskey xray yankee zulu. More filler to reach the threshold and
ensure no additional validators trigger on this note beyond template non-compliance.
