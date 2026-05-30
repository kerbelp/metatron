# CLAUDE.md

Ground rules for working in this repo. Read this first.

## What Metatron is

Metatron is a self-hosted system that captures a company's real implementation
decisions — preferred patterns, rejected approaches, edge cases, internal
conventions — as structured **priors**, and serves them to coding agents over MCP
(Model Context Protocol). The goal is for an agent to write code like a senior
engineer who already knows this codebase. It runs against a private codebase, so
assume sensitive data and on-prem deployment.

## Tech stack (decided — not open for debate)

These are locked. Do not re-litigate or substitute them:

- **Python 3.12+**
- **Official MCP Python SDK** for the server
- **tree-sitter** for language-agnostic code parsing
- **SQLite** for the prior store — but always behind a storage interface, because
  the schema must be portable to Postgres later
- **pytest** for tests
- **uv** for dependency management

## Core principle

- Priors are stored as **structured records** (fields: pattern, context/scope,
  rationale, confidence, source refs) — **never** as prose specs.
- **Nothing enters the canonical set without human curation.** No prior
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
- Web UI
- Auth, multi-tenant, RBAC
- Jira / ticket / postmortem ingestion (a later source)
- Postgres (use SQLite now, behind the storage interface)
- Deployment infra and packaging for distribution
