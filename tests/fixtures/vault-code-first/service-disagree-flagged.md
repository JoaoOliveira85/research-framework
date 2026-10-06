---
title: Service Disagree Flagged
type: service
tags: [service]
created: 2026-04-17
updated: 2026-04-17
status: draft
summary: "Code says 3 retries; intent says 5 — properly flagged"
related: []
source_urls:
  - url: "file:///repo/oehk-service/application.yml"
    title: "application.yml"
    accessed: 2026-04-17
  - url: "https://example.atlassian.net/wiki/x"
    title: "OEHK intent"
    accessed: 2026-04-17
confidence: high
scope: team
template_version: "1.0.0"
intent_implementation_drift: true
drift_notes:
  - fact: retries
    code_value: "3"
    intent_value: "5"
  - fact: timeout
    code_value: "500"
    intent_value: "1000"
intent_status: captured
source_quality: high
---

# Service Disagree Flagged

## Overview

Tests properly flagged drift.

## Current Behaviour

Retries: 3. Timeout: 500ms. Owner: Platform.

## Stated Intent

Retries: 5. Timeout: 1000ms. Owner: Platform.

## Dependencies

None.

## Risks

None.

## Why It Matters

Correctly flagged drift passes validation.
