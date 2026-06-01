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

**Milestone 1 complete** — a thin end-to-end vertical slice validating one
question: *can we bootstrap useful priors from a real codebase + its git history
and serve them to an agent over MCP?* See [PLAN.md](PLAN.md) for the design and
[CLAUDE.md](CLAUDE.md) for working ground rules.

Priors are stored as **structured records** (pattern, scope, rationale,
confidence, source refs), and **nothing becomes canonical without human
curation** — bootstrapped and agent-submitted priors both start as candidates.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
uv sync
```

Ingest uses the Anthropic API by default, so provide a key. The CLI auto-loads a
`.env` file from the working directory (it never overrides an already-exported
variable, and `.env` is gitignored):

```bash
# .env in the repo root
ANTHROPIC_API_KEY=sk-...
```

or export it directly with `export ANTHROPIC_API_KEY=sk-...`. Only `ingest`
needs the key — `serve` and `candidates` are fully local.

Non-secret settings live in an optional `metatron.toml` (env vars override it):

```toml
[metatron]
db_path = "metatron.db"
model = "claude-opus-4-8"
```

## The loop: ingest → curate → serve

### 1. Ingest — bootstrap candidate priors from a repo + its git history

```bash
uv run metatron ingest /path/to/your/repo
# optional: --max-commits 1000 --since 2024-01-01 --path src/ --repo <id>
```

This parses git-tracked source files (tree-sitter) and reads commit history,
aggregates per-area signals, asks the model to infer priors, and stores them as
**candidates**.

Priors and usage are keyed by a **repo identity** derived from the repo's
`origin` remote (constant across developers; a local checkout path isn't), with a
`--repo` override and a directory-name fallback when there's no remote. One DB
holds many repos; each is isolated on retrieval.

### 2. Curate — humans decide what becomes canonical

```bash
uv run metatron candidates list              # review candidates (optionally --scope app/storage)
uv run metatron candidates approve <id>      # promote to the canonical set
uv run metatron candidates reject <id>       # discard
```

For large candidate queues, run the **advisory triage judge** first — a separate
LLM pass that scores each candidate (recommended / borderline / not-recommended)
with a reason, so you curate a ranked, pre-filtered queue. It **does not
auto-curate** — the human still approves; nothing self-promotes.

```bash
uv run metatron triage --repo <id>     # then filter by recommendation in the UI
```

Or use the local web UI (browse paginated, filter by status/scope/recommendation,
approve/reject with a click). It binds to `localhost:1337`, bumping to the next free port if
taken, and reads/writes the same store as the CLI:

```bash
uv run metatron ui            # then open the printed http://127.0.0.1:<port>
uv run metatron ui --port 9000
```

The UI also has an **Observability** tab showing usage: how often agents query,
coverage (the share of queries that returned a canonical prior), most-queried
scopes, and recent queries. `metatron serve` records these usage events to the
same DB — so run `serve` for your agent and watch the tab populate. (Usage only;
no token accounting or helpfulness judgments are recorded.)

### 3. Serve — expose canonical priors to agents over MCP

```bash
uv run metatron serve --repo <id>    # MCP server over stdio, for one repo
```

One served instance serves one repo (`--repo`, the id printed by `ingest`), so an
agent only ever sees that repo's priors. The web UI, by contrast, spans all repos
in the DB with a repo selector.

### Onboarding a repo's agent

So a coding agent reliably *consults* the priors (rather than rediscovering
conventions), run the onboarding script from inside the target repo:

```bash
bash /path/to/metatron/metatron_setup.sh        # or pass the repo dir as an arg
```

It is **additive and idempotent** — it (1) appends a "query Metatron first" block
to `CLAUDE.md` (between markers, never deleting your content), (2) merges a
`UserPromptSubmit` hook into `.claude/settings.json` (preserving existing config)
that re-injects the directive every turn, and (3) adds the `metatron` MCP server
to `.mcp.json` (created if absent; existing servers preserved; left alone if a
`metatron` server is already defined). The repo id is derived from the repo's
`origin` remote (override with `METATRON_REPO`). Then just reconnect the agent.

Two tools are exposed:

- `get_priors_for_context(file_path_or_area, task_description)` → the relevant
  **canonical** priors as compact structured context.
- `submit_candidate_learning(pattern, scope, rationale, confidence)` → records a
  prior an agent learned in practice as a new **candidate** (never auto-promoted).

Point an MCP-capable agent at the server. Example client config:

```json
{
  "mcpServers": {
    "metatron": {
      "command": "uv",
      "args": ["run", "metatron", "serve"],
      "env": { "METATRON_DB": "/abs/path/to/metatron.db" }
    }
  }
}
```

## Development

```bash
uv run pytest          # run the test suite
```

## Tech stack

Python 3.12+, the official MCP Python SDK, tree-sitter for parsing, SQLite
(behind a storage interface, portable to Postgres later), pytest, and uv. These
are decided — see [CLAUDE.md](CLAUDE.md).
