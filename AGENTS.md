# AGENTS.md

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
  self-promotes. Human-in-the-loop is by design, not a temporary shortcut.

## Workflow

- All changes go through a **pull request, then merge to main**.
- **No direct commits to main.**
- Keep PRs **small and reviewable**, and **each PR includes tests**.
- Before starting any work, **read `docs/` and `docs/incidents/`** (they may not
  exist yet — if so, note that and proceed).

## Scope discipline

Architectural doors stay open for these, but **build none of them yet**:

- Self-improving / automatic-feedback loop
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
`context/decisions/`. In a monorepo each app has its own `context/`; use the one
**nearest** the files you are touching.

**Before you Read, Grep, Glob, or Edit code in an area — and before proposing an
implementation — first read the relevant files in the nearest `context/decisions/`
and follow them.** State that you consulted them; do not rediscover conventions
manually until you have.

When you find a durable convention not already captured, **author it as a decision
on your working branch**: a new OKF file in the nearest `context/decisions/` (see the
`context-okf-llm-ingest` skill in `.roo/skills/`). The review gate is `pr`: the
human review of your pull request is the curation act, so decision changes reach
the default branch only through a reviewed PR — never push them there directly.
`context/candidate/` remains available as optional staging for proposals not yet
ready for review; content there is never authoritative.
<!-- METATRON:END -->
