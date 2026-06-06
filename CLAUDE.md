# CLAUDE.md

Ground rules for working in this repo. Read this first.

## What Metatron is

Metatron is a self-hosted system that captures a company's real implementation
decisions — preferred patterns, rejected approaches, edge cases, internal
conventions — as structured **decisions**, and serves them to coding agents over MCP
(Model Context Protocol). The goal is for an agent to write code like a senior
engineer who already knows this codebase. It runs against a private codebase, so
assume sensitive data and on-prem deployment.

## Tech stack (decided — not open for debate)

These are locked. Do not re-litigate or substitute them:

- **Python 3.12+**
- **Official MCP Python SDK** for the server
- **tree-sitter** for language-agnostic code parsing
- **SQLite** for the decision store — but always behind a storage interface, because
  the schema must be portable to Postgres later
- **pytest** for tests
- **uv** for dependency management

## Core principle

- Decisions are stored as **structured records** (fields: pattern, context/scope,
  rationale, confidence, source refs) — **never** as prose specs.
- **Nothing enters the canonical set without human curation.** No decision
  self-promotes. **Crossing the canonical boundary — promote, demote, reject —
  is always human-gated.** This invariant is absolute.

## Partial self-learning loop (2026-06-03)

Metatron now has a **bounded** self-learning loop, so the "no automatic feedback
loop" stance below is no longer absolute — read this carefully before assuming a
change violates it:

- Agents rate served decisions 1–10 (`submit_feedback`). A time-decayed, shrunk score
  **automatically reorders which canonical decisions are served first**.
- This auto-weighting **only reorders *within* a scope/relevance tier**. It can sink a
  misleading decision below the serve limit, but it **never crosses the canonical
  boundary** — no auto-promote, auto-demote, or auto-reject. The Core principle above
  still holds in full.
- See `docs/designs/2026-06-03-decision-helpfulness-rating.md` and
  `docs/future-features.md` item **C** (now partially built). Full unsupervised
  mutation of decisions remains deferred.

## Workflow

- All changes go through a **pull request, then merge to main**.
- **No direct commits to main.**
- Keep PRs **small and reviewable**, and **each PR includes tests**.
- Before starting any work, **read `docs/` and `docs/incidents/`** (they may not
  exist yet — if so, note that and proceed).

## Scope discipline

Architectural doors stay open for these, but **build none of them yet**:

- Self-improving / automatic-feedback loop — **partially built**: serve-ordering
  auto-weighting is live (see "Partial self-learning loop" above); *unsupervised
  mutation* of decisions across the canonical boundary stays deferred
- Telemetry ingestion
- Auth, multi-tenant, RBAC, and any hosted/multi-user web app
- Jira / ticket / postmortem ingestion (a later source)
- Postgres (use SQLite now, behind the storage interface)
- Deployment infra and packaging for distribution

A **local, single-user curation web UI** (`metatron ui`, bound to localhost) is
in scope — it's a thin local view over the same `DecisionStore` the CLI uses. The
out-of-scope item is a hosted/multi-user web app with auth, not this.
