---
title: Service Prose Difference
type: service
tags: [service]
created: 2026-04-17
updated: 2026-04-17
status: draft
summary: "Prose-only difference; v1 heuristic does not flag"
related: []
source_urls:
  - url: "file:///repo/oehk-service/README.md"
    title: "README"
    accessed: 2026-04-17
  - url: "https://example.atlassian.net/wiki/x"
    title: "intent"
    accessed: 2026-04-17
confidence: medium
scope: team
template_version: "1.0.0"
intent_implementation_drift: false
drift_notes: []
intent_status: captured
source_quality: medium
---

# Service Prose Difference

## Overview

Narrative-only differences; no structured facts.

## Current Behaviour

The service is fast, handles many cases, and is generally reliable under load.

## Stated Intent

The service should be slow, handle fewer cases, and be unreliable under load.

## Dependencies

None.

## Risks

None.

## Why It Matters

Narrative differences are not caught by the v1 heuristic (conservative scope).
