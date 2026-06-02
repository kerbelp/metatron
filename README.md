# Metatron

Metatron is a self-hosted system that captures a codebase's real implementation
decisions — preferred patterns, rejected approaches, edge cases, internal
conventions — as structured **priors**, and serves them to coding agents over
MCP (Model Context Protocol). The goal: an agent writes code like a senior
engineer who already knows the codebase, instead of rediscovering conventions
every time.

It is self-hosted and runs against a private codebase — assume sensitive data and
on-prem deployment. (Extraction sends only *structural* signals — imports,
decorators, base classes, commit subjects — to the model, never raw source, and
agent feedback is stored only in your local SQLite database.)

- **Priors are structured records**, not prose: `pattern`, `scope`, `rationale`,
  `confidence`, `source_refs`.
- **Nothing becomes canonical without a human.** Bootstrapped, agent-submitted, and
  feedback-refined priors all start as **candidates** for curation; none self-promote.

See [PLAN.md](PLAN.md) for the design and [CLAUDE.md](CLAUDE.md) for working ground
rules.

## How it works — the loop

```
            ┌─────────── ingest ───────────┐
 your repo ─┤  parse (tree-sitter) + git    ├─▶ candidate priors
            └──────── LLM extraction ───────┘          │
                                                       ▼
                                              curate (human)  ◀── triage (advisory)
                                                       │  approve / reject
                                                       ▼
 coding agent ◀──── serve (MCP) ──── canonical priors
       │
       └── submit_feedback (what was missing) ──▶ refine-feedback ──▶ candidate priors ──▶ curate
```

Bootstrap once with `ingest`, curate candidates into the canonical set, then `serve`
them to your agent over MCP. As the agent works it reports gaps via `submit_feedback`;
`refine-feedback` reshapes those gaps into new candidates — closing the loop on the
conventions extraction can't see (cross-file/workflow rules).

## Requirements

- [uv](https://docs.astral.sh/uv/) (dependency + environment manager)
- Python 3.12+
- An Anthropic API key — only for the LLM steps (`ingest`, `triage`, `refine-feedback`).
  `serve`, `ui`, and `candidates` are fully local and need no key.

## Installation

```bash
git clone https://github.com/getmetatron/metatron.git
cd metatron
uv sync           # create the venv and install dependencies
```

Run the CLI without installing anything globally:

```bash
uv run metatron --help
```

Or install it as a global tool so `metatron` is on your PATH anywhere:

```bash
uv tool install .       # then just: metatron --help
```

> The examples below use `uv run metatron`. If you installed globally, drop the
> `uv run` prefix.

### Configuration

**Secrets** come from the environment only. The CLI auto-loads a `.env` from the
working directory (it never overrides an already-exported variable, and `.env` is
gitignored):

```bash
# .env in the repo root
ANTHROPIC_API_KEY=sk-ant-...
```

…or `export ANTHROPIC_API_KEY=sk-ant-...` directly.

**Non-secret settings** live in an optional `metatron.toml` (environment variables
`METATRON_DB` / `METATRON_MODEL` override it):

```toml
[metatron]
db_path = "metatron.db"        # one SQLite file holds many repos
model   = "claude-sonnet-4-6"  # default extraction model
```

## Quick start

```bash
uv run metatron ingest /path/to/your/repo      # 1. bootstrap candidates (needs API key)
uv run metatron candidates list                # 2. review …
uv run metatron candidates approve <id>        #    … and curate
uv run metatron serve --repo <id>              # 3. serve canonical priors over MCP
```

`ingest` prints the `<id>` to use for `serve`. To wire it into a coding agent
automatically, see [Connecting a coding agent](#connecting-a-coding-agent-mcp).

## Command reference

```text
$ uv run metatron --help
usage: metatron [-h] {ingest,serve,ui,triage,refine-feedback,candidates} ...

positional arguments:
  {ingest,serve,ui,triage,refine-feedback,candidates}
    ingest              bootstrap candidate priors from a repo
    serve               serve one repo's priors to agents over MCP
    ui                  launch the local curation web UI
    triage              run the advisory judge over candidate priors (does not auto-curate)
    refine-feedback     reshape captured agent feedback into structured candidate priors (Opus)
    candidates          review and curate candidate priors
```

### `ingest` — bootstrap candidate priors from a repo + its git history

Parses git-tracked source files (tree-sitter) and reads commit history, aggregates
per-area signals, asks the model to infer priors, and stores them as **candidates**.

```text
$ uv run metatron ingest /path/to/your/repo
Ingested repo 'github.com/acme/app' from /path/to/your/repo: parsed 214 files, read 500 commits across 38 scopes, created 271 candidate priors.
Review them with: metatron candidates list --repo github.com/acme/app
Serve them with:  metatron serve --repo github.com/acme/app
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--max-commits N` | `500` | how much git history to read |
| `--since DATE` | — | only commits after e.g. `2024-01-01` |
| `--path SUBTREE` | — | limit ingest to a subtree, e.g. `src/components` |
| `--repo ID` | origin remote | override the repo identity |

Priors and usage are keyed by a **repo identity** derived from the repo's `origin`
remote (constant across developers; a checkout path isn't), with a `--repo` override
and a directory-name fallback when there's no remote. One DB holds many repos; each
is isolated on retrieval.

### `candidates` — review and curate (humans decide what becomes canonical)

```text
$ uv run metatron candidates list
1d2ab8e8-e674-4fbd-9875-52bf065e94c1  [high]  (CheckoutSuccessRedirect (paid submit/finish flow))
    After a paid submission completes via CheckoutSuccessRedirect, redirect the user to /my-dashboard/?thanks=1 rather than the public app page.
d672a984-dd56-4974-8111-5ff730a6ed50  [high]  (src/utils/misc/index.ts (makePrettyUrl and any slug generation))
    Any slug-from-name code (e.g. `makePrettyUrl`) must strip "/" characters so a name like "LangChain / LangSmith" does not produce a link_name with slashes that break routing.

$ uv run metatron candidates approve 1d2ab8e8-e674-4fbd-9875-52bf065e94c1
Prior 1d2ab8e8-e674-4fbd-9875-52bf065e94c1 approved.

$ uv run metatron candidates reject d672a984-dd56-4974-8111-5ff730a6ed50
Prior d672a984-dd56-4974-8111-5ff730a6ed50 rejected.
```

`candidates list` accepts `--repo <id>` and `--scope <path>` filters. `approve`
promotes a candidate to canonical; `reject` discards it.

### `triage` — advisory judge over the candidate queue (does not auto-curate)

For large candidate queues, a separate LLM pass scores each candidate
(recommended / borderline / not-recommended) with a reason, so you curate a ranked,
pre-filtered queue. It **does not curate** — a human still approves.

```text
$ uv run metatron triage --repo github.com/acme/app
Triaged 271 candidates: approve=88, borderline=96, reject=87
  judge cost: ~$0.42
Review by recommendation in the UI's Candidates filter.
```

Flags: `--repo <id>` (limit to one repo), `--limit N` (max candidates to judge).

### `serve` — expose canonical priors to agents over MCP

```bash
uv run metatron serve --repo github.com/acme/app    # MCP server over stdio, one repo
```

One served instance serves exactly one repo (`--repo`, the id printed by `ingest`),
so an agent only ever sees that repo's priors. It also records usage events (queries,
coverage) to the same DB for the UI. Normally you don't run this by hand — an
MCP-capable agent launches it (see below).

### `ui` — local curation web UI

```text
$ uv run metatron ui
Metatron curation UI on http://127.0.0.1:1337  (Ctrl-C to stop)
```

Binds to `localhost` (bumping to the next free port if taken) and reads/writes the
same store as the CLI. Tabs:

- **Priors** — browse paginated; filter by status / scope / triage recommendation /
  origin; full-text search; approve/reject with a click.
- **Usage** — how often agents query, coverage (share of queries that returned a
  prior), most-queried scopes, recent queries.
- **Quality** — prior quality by origin (ingest vs feedback) and one-time ingest cost.
- **Feedback** — the agent feedback stream, filterable **All / Unhandled / Handled**.
  Handled reports expand to show the candidate priors they were refined into, each
  with its curation status and usefulness (served / 👍 / 👎). Unhandled reports get a
  **Refine into priors** button to run the refiner on that one report on the spot.

Flag: `--port N` (starting port, default `1337`).

### `refine-feedback` — reshape captured agent feedback into candidates

When an agent reports a missing convention via `submit_feedback`, this reshapes those
free-text gap reports into **structured candidate priors** (defaults to Opus, the
higher-stakes step). Nothing it produces is canonical — it all goes to curation.

```text
$ uv run metatron refine-feedback
Refined 3 feedback report(s) into 13 candidate prior(s) for curation.
  refiner cost: ~$0.19
Review them in the UI Candidates tab (origin: feedback).
```

Flags: `--repo <id>`, `--limit N` (max reports to refine), `--model <name>`
(override the refiner model).

## Connecting a coding agent (MCP)

So a coding agent reliably *consults* the priors (rather than rediscovering
conventions), run the onboarding script from inside the target repo:

```bash
bash /path/to/metatron/metatron_setup.sh        # or pass the repo dir as an arg
```

It is **additive and idempotent**, and adds (never deletes) four things to the target
repo:

1. A "query Metatron first" block in `CLAUDE.md` (between markers).
2. A `UserPromptSubmit` hook in `.claude/settings.json` that re-injects the directive
   every turn.
3. A **`Stop` hook** that, when the agent finishes a task where it consulted Metatron
   but never sent feedback, reminds it (once per session) to call `submit_feedback`.
4. The `metatron` MCP server in `.mcp.json`.

The repo id is derived from the `origin` remote (override with `METATRON_REPO`).
Then reconnect the agent so it loads the hooks and server.

### MCP tools exposed

| Tool | Purpose |
|------|---------|
| `get_priors_for_context(file_path_or_area, task_description)` | the relevant **canonical** priors as compact structured context, with a `query_id` to reference in feedback |
| `submit_feedback(query_id, helpful, unhelpful, what_was_missing, missing_scope)` | rate served priors by `[index]` and report a convention Metatron should have known — captured for `refine-feedback`; never auto-applied |
| `submit_candidate_learning(pattern, scope, rationale, confidence)` | record a convention the agent learned as a new **candidate** (never auto-promoted) |

A `get_priors_for_context` call returns context like this:

```text
metatron:query b1f2… · rev 1101886 (reference the query id in submit_feedback)
[1] [medium] Record payment/sale events into the shared payments ledger when handling subscription billing.
  scope: src/routes/api/subscription
  why: A fix commit explicitly records LemonSqueezy sales into the payments ledger, establishing this as the expected billing-recording pattern for this scope.
[2] [high] serviceForProduct must classify every billable product — including the standard $19 'Publish Now' listing — and never return null, because recordPayment silently drops unclassified products from the payments ledger.
  scope: src/routes/api/subscription/index.ts
  why: Returning null caused listing revenue to never reach the ledger or the admin Payments tile.
```

### Manual MCP client config

If you wire the server up yourself instead of using the script:

```json
{
  "mcpServers": {
    "metatron": {
      "command": "uv",
      "args": ["run", "--project", "/abs/path/to/metatron", "metatron", "serve", "--repo", "github.com/acme/app"],
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

Python 3.12+, the official MCP Python SDK, tree-sitter for parsing, SQLite (behind a
storage interface, portable to Postgres later), pytest, and uv. These are decided —
see [CLAUDE.md](CLAUDE.md).
