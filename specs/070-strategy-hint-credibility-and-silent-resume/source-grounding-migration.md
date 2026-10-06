# Grounding long-tail citations — the two supported mechanisms

**Status:** verified 2026-08-26 against `~/Documents/vaults/community-vault`.
Replaces `settings-override-example.yaml`, which was a 24-domain
`trusted_domains` blob kept as an acknowledged *workaround* for F1. With FR1
shipped, most of that blob becomes a **declaration in the spec** — the supported
path — and only the multi-tenant remainder stays an override.

## Why there are two mechanisms, not one

A citation's host is either **owned by the source** or **rented from a platform**.

| The host is… | Example | Mechanism | Why |
|---|---|---|---|
| owned by the thing being cited | `conf-two.example`, `person-a.example`, `engineering.bravo.example` | `data_sources[].urls` in `research.spec.md` | The vault author already knows these; the source *is* the domain, so the source's `default_credibility` is exactly right for it. |
| a multi-tenant platform | `medium.com`, `dev.to`, `linkedin.com` | `settings.yaml::credibility.trusted_domains` with `match_type: host_path` | One tenant must not grade the whole platform. `medium.com/bravo-engineering` is evidence; `medium.com` is not. |

Declaring a platform host under `urls:` would ground **every** page on it at the
source's level. That is the one real footgun in FR1, and path-scoping in the
override is the tool that exists for it.

## Mechanism 1 — enumerate the source's own domains (spec 070 FR1)

A `kind: strategy_hint` source is routinely a *set* of domains. `url:` names one
representative; `urls:` names the rest. Both are indexed host-scoped — never as a
subdomain wildcard, so `engineering.bravo.example` does not ground `bravo.example`.

```yaml
data_sources:
  - name: "Regional company engineering blogs"
    kind: strategy_hint
    role: domain
    default_credibility: primary
    url: "https://eng.alpha.example/"
    urls:
      - "https://engineering.bravo.example/"
      - "https://engineering.charlie.example/"
      - "https://tech.delta.example/"
      - "https://blog.echo.example/"

  - name: "Regional conference sites"
    kind: strategy_hint
    role: domain
    default_credibility: primary
    url: "https://conf-one.example/"
    urls:
      - "https://conf-two.example/"
      - "https://www.conf-three.example/"
      - "https://conf-four.example/"
      - "https://conf-five.example/"
      - "https://conf-six.example/"
      - "https://conf-seven.example/"

  - name: "Practitioner personal sites and open source"
    kind: strategy_hint
    role: domain
    default_credibility: primary
    url: "https://github.com/"
    urls:
      - "https://person-a.example/"
      - "https://www.person-a.example/"
      - "https://person-b.example/"
      - "https://artemis.person-b.example/"
```

> **`www.` is a different host.** `person-a.example` and `www.person-a.example` must both be
> listed if the notes cite both. Host matching is exact by design — a suffix rule
> would ground far more than the author declared.

> **`url: "https://github.com/"` grounds all of GitHub at `primary` for this
> vault.** That is what the declaration says, and it is honoured. If that is
> broader than intended, drop it from the source and rely on the shipped catalog
> — spec 070 F2 relaxed `github.com` to `min_segments: 1`, so profiles and
> repositories both ground at `corroborated` with no vault configuration at all.

## Mechanism 2 — path-scope the multi-tenant platforms (spec 066 FR3)

```yaml
# settings.yaml
credibility:
  trusted_domains:
    - { domain: "medium.com",       tier: tier_3, match_type: host_path, min_segments: 1 }
    - { domain: "dev.to",           tier: tier_3, match_type: host_path, min_segments: 1 }
    - { domain: "www.linkedin.com", tier: tier_3, match_type: host_path, min_segments: 2 }
```

`tier_3` ⇒ `commentary`, which is the honest level for self-published platform
content. `min_segments` keeps the bare platform host ungrounded.

## Verified result

Applied to a copy of the subject vault, with the hand-added per-citation
`credibility:` fields **stripped**, all nine previously-quarantined notes
resolve every citation:

```
person_c  person_b  person_a  conf_two  conf_four
community_e  publisher_f  bravo_engineering_blog  charlie_engineering_blog
                                                            → 9/9 PASS
```

That is spec 070's T015 / T050 acceptance criterion, met with declared
configuration only — no per-citation hand edits, and no blanket wildcard.

## Applying it to a vault that already has quarantined notes

Do **not** hand-restore notes into `data_vault/`. The quarantine sweep
(`orchestrator._quarantine_rejected_notes`) keys off frontmatter
`verifier_status: rejected` and does not re-verify, so a hand-restored note is
swept straight back out on the next run — see F7. Use the deterministic verb,
which re-grades against the current model and reinstates what now resolves:

```bash
./vault re-grade
```
