---
title: Fingerprint Variant
type: concept
template_version: "1.0.0"
_template_version: 1
verifier_status: approved
summary: How the device fingerprint variantId is selected during onboarding.
tags: [onboarding, fingerprint]
source_urls:
  - url: https://github.com/acme-corp/oebh-service/pull/1421
    credibility: primary
    coi: false
related:
  - "[[Cohort Drift]]"
created: 2026-06-01
updated: 2026-06-04
---

## Overview

The `variantId` is resolved from the device fingerprint vector before the
cohort is assigned. This is the load-bearing behaviour the GOLD P1 probe
traps.

## Related

- [[Cohort Drift]]
