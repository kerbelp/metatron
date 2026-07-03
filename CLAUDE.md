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

## Source of truth (depends on deployment)

Metatron supports two ways of operating, and the source of truth differs:

- **MCP / database mode (default).** SQLite is the source of truth; the git-tracked
  OKF markdown bundle is a synced mirror (`metatron mirror sync`). Curation happens in
  the store (CLI/UI), and decisions are served to agents over MCP.
- **Files-first mode (no MCP).** For teams that want to avoid MCP, the git-tracked OKF
  files are the source of truth: the directory (`candidate/` vs `decisions/`) is the
  status, decisions are curated as plain files reviewed via pull request, and the
  database is a derived, rebuildable serving index (`metatron mirror import`).

The **canonical boundary stays human-gated in both modes** (see Core principle):
nothing self-promotes; a human placing or moving a file into `decisions/` — or
approving the pull request that does — is the curation act.

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
- **This is a public repo. Write every commit message and PR description as a
  neutral, third-person technical note.** Describe the change and its rationale —
  not how it was requested. **Never** reference the chat or agent session, "the
  user", "you", "we just", "live-testing", screenshots, or any conversation
  context in commit/PR text. (Same goes for code comments.)

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

<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Codebase conventions via Metatron (files) — consult FIRST

This repo's conventions ("decisions") live as Open Knowledge Format markdown under
`context/` — `context/decisions/` is canonical, `context/candidate/` is proposed
(unreviewed). In a monorepo each app has its own `context/`; use the one **nearest**
the files you are touching.

**Before you Read, Grep, Glob, or Edit code in an area — and before proposing an
implementation — first read the relevant files in the nearest `context/decisions/`
and follow them.** State that you consulted them; do not rediscover conventions
manually until you have.

When you find a durable convention not already captured, **author it as a candidate**:
a new OKF file in the nearest `context/candidate/` (see the `okf-llm-ingest` skill in
`.roo/skills/`). Candidates are uncurated proposals for human review.

**Promotion to canonical is human-gated.** Never move a file into `context/decisions/`
yourself; a human does that via `git mv` reviewed in a pull request (see the
`okf-promote-candidates` skill). Nothing self-promotes.
<!-- METATRON:END -->
