# Metatron

Metatron is a self-hosted system that captures a company's real implementation
decisions — preferred patterns, rejected approaches, edge cases, internal
conventions — as structured **priors**, and serves them to coding agents over
MCP (Model Context Protocol). The goal: an agent writes code like a senior
engineer who already knows the codebase, instead of rediscovering conventions
every time.

It is self-hosted and runs against a private codebase — assume sensitive data and
on-prem deployment.

## Status

**Milestone 1 — in progress.** A thin end-to-end vertical slice validating one
question: *can we bootstrap useful priors from a real codebase + its git history
and serve them to an agent over MCP?* See [PLAN.md](PLAN.md) for the design and
[CLAUDE.md](CLAUDE.md) for working ground rules.

Nothing below is implemented yet — it describes the loop the milestone is
building toward. This section becomes a real walkthrough as the PRs land.

## The loop (target)

```
# 1. Ingest — bootstrap candidate priors from a local repo + its git history
metatron ingest /path/to/your/repo

# 2. Curate — humans promote candidates into the canonical set (nothing self-promotes)
metatron candidates list
metatron candidates approve <id>
metatron candidates reject <id>

# 3. Serve — expose canonical priors to agents over MCP
metatron serve
```

## Tech stack

Python 3.12+, the official MCP Python SDK, tree-sitter for parsing, SQLite
(behind a storage interface, portable to Postgres later), pytest, and uv for
dependency management. These are decided — see [CLAUDE.md](CLAUDE.md).
