# OKF v0.2 conformance: trust signals on decisions

**Status:** proposed
**Scope:** files-first bundle format, `context setup` scaffolding, mirror
export/import, serve-side filtering. No storage-schema change.

## Background

OKF v0.2 (announced 2026-07-25) adds an opt-in frontmatter vocabulary for
deciding about a concept before reading it: `generated` (provenance of
authorship), `verified` (verification events), `status` + lifecycle,
`stale_after` (freshness), `sources` (input provenance), and attestation
hooks. `type` remains the only required field; unknown keys remain preserved;
a v0.1 bundle is a valid v0.2 bundle.

Metatron's model already produces every one of these signals operationally —
it just doesn't write them down in the exported frontmatter:

| v0.2 field | Existing Metatron fact |
|---|---|
| `generated: {by, at}` | which extractor/agent authored the candidate, and when |
| `verified: [{by, at}]` | the review-gate event: the human merge (gate `pr`) or explicit promote (CLI/UI) |
| `status` | directory status: `candidate/` vs `decisions/`; superseding entries |
| `stale_after` | not tracked today (new, optional) |
| `sources` | source refs already stored on decisions (code refs, commits, sessions) |
| attestation | verification contracts (0.13) run against a decision's scope |

The review gate is what makes these signals meaningful: `verified:` entries
are only ever written as a *consequence* of a gate event, never self-asserted
by the authoring agent. Conformance therefore adds vocabulary without touching
the core invariant — the canonical boundary stays human-gated.

## Changes

### 1. Decision file frontmatter (writer)

`mirror export` / files-first writers add, when known:

```yaml
type: Metatron Decision            # unchanged, still the only required key
title: ...
scope: ...
confidence: ...
generated: { by: "agent:<model-or-tool>", at: <iso8601> }
verified:
  - { by: "human:<reviewer-or-pr>", at: <iso8601> }   # written on promote only
status: stable                     # candidate | stable | superseded
stale_after: <date>                # optional, author- or curator-set
sources:
  - { id: <slug>, resource: <path-or-url>, title: ... }
```

Rules:
- `verified` is append-only and written exclusively by the promote path
  (gate event); the ingest/candidate path can never produce it.
- `status: candidate` is implied by the `candidate/` directory and omitted
  there; `stable` is written on promote; `superseded` on supersede.
- All fields optional on read: bundles without them import unchanged.

### 2. Reader / serve-side

- Parse the new fields when present; expose them on the serve payload.
- New serve filter knobs (all default-off): `min_verification` (require ≥1
  `verified` entry), `exclude_stale` (drop entries past `stale_after`),
  provenance surfacing in the served index line.

### 3. Verification contracts as attesters

A contract run that passes against a decision's scope MAY append a
`verified: {by: "contract:<name>", at: ...}` entry. Contract entries are
distinguishable from human entries by the `by:` prefix and never satisfy the
canonical-boundary requirement on their own.

### 4. Explicitly out of scope

- No change to the SQLite schema (signals derive from existing columns plus
  file frontmatter round-tripping).
- No change to research harnesses; historical bundles remain valid v0.1.
- No auto-verification: agents cannot write `verified:` for themselves.

## Migration

None required. Existing bundles are valid as-is; new fields appear on the
next export/promote. A `metatron mirror export --okf-v02` flag gates the new
fields for one release, then becomes the default.

## Testing

- Round-trip: export → import preserves the new fields and unknown keys.
- Gate coupling: promote writes `verified`; ingest cannot; supersede flips
  `status`.
- Filters: `min_verification` / `exclude_stale` behavior on mixed bundles.
