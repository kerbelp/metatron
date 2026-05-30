# PLAN.md — First Milestone

> Status: **proposal, awaiting approval.** This is the design doc for the first
> milestone. Nothing here is built yet. Comment in the PR; finer decisions are
> flagged as **Open questions** at the bottom.

## Goal (restated)

Validate the single riskiest assumption: *can we automatically bootstrap useful
priors from a real codebase + its git history, and serve them to an agent over
MCP in a way that would plausibly change what the agent writes?*

A thin end-to-end vertical slice: **ingest → store → serve → curate.**

## Decisions locked in brainstorming

- **Validation target:** a real (private) git repo provided by a local path at
  run time. It will not be checked into this repo or its tests.
- **Parsing:** language-agnostic abstraction now; the concrete tree-sitter
  grammar is wired once we know the target repo's language. One reference grammar
  is wired so the slice is runnable/testable end-to-end (proposed: Python).
- **LLM provider:** Anthropic Claude is the default, behind a provider interface.
  Trade-off accepted: ingest sends code/diffs to Anthropic's API; the interface
  keeps a local/on-prem model open for later.

## Module structure

A single installable package `metatron`, organized so each unit has one clear
purpose and a stable interface. Storage, parsing, and the LLM provider are all
behind interfaces (the portability/configurability the brief requires).

```
metatron/
  config.py              # Settings: provider, model, repo path, db path; reads env / file
  models.py              # Prior, SourceRef, enums (Status, Origin, Confidence). pydantic.

  storage/
    base.py              # PriorStore (ABC) — the storage interface
    sqlite.py            # SQLitePriorStore — SQLite implementation behind the ABC

  parsing/
    base.py              # LanguageParser (ABC), ParsedFile, StructuralSummary
    registry.py          # language -> parser registry; grammars wired here
    python_parser.py     # reference grammar (proposed); more added later

  gitlog/
    reader.py            # walk commits: messages, diffs, churn — via `git` subprocess

  extraction/
    signals.py           # deterministic signal collection (parsing + gitlog -> facts)
    provider.py          # LLMProvider (ABC) + AnthropicProvider
    extractor.py         # orchestrates: signals -> prompt -> LLM -> candidate Priors
    prompts/             # editable prompt templates (plain text, {placeholder} subst.)

  mcp/
    server.py            # MCP server: get_priors_for_context, submit_candidate_learning

  pipeline.py            # ingest orchestration (point at a repo path)
  cli.py                 # entrypoint: ingest / serve / candidates list|approve|reject

tests/                   # pytest, one area per module; fixtures use tiny synthetic repos
```

## Prior data schema (the structured record)

Priors are **structured records, never prose**. Proposed fields (pydantic model,
mirrored in the SQLite schema):

| Field         | Type                          | Notes |
|---------------|-------------------------------|-------|
| `id`          | str (uuid4)                   | stable id |
| `pattern`     | str                           | the prescriptive statement ("Use X for Y") |
| `scope`       | str                           | where it applies: path glob / module / language / `global` |
| `rationale`   | str                           | why this is the convention |
| `confidence`  | enum `low \| medium \| high`  | legible to humans; see open Q on float vs enum |
| `source_refs` | list[SourceRef]               | provenance — see below |
| `status`      | enum `candidate \| canonical \| rejected` | **default `candidate`** |
| `origin`      | enum `bootstrap \| agent_submitted`       | how it entered the store |
| `created_at`  | datetime                      | |
| `updated_at`  | datetime                      | |

`SourceRef` = `{ kind: file \| commit, ref: <path or SHA>, detail: str }`.

**Core principle enforced here:** every prior — including bootstrapped ones from
ingest — starts as `candidate`. Nothing becomes `canonical` except via the
curation CLI. Ingest does not self-promote.

Storage stays portable to Postgres: the SQLite DDL uses portable types (TEXT,
INTEGER, TIMESTAMP), `source_refs` stored as JSON text, all access through the
`PriorStore` ABC so the SQL never leaks into callers.

## Extraction approach (the riskiest part)

Three options considered:

- **(A) Two-pass: deterministic signals → focused LLM extraction (recommended).**
  First collect cheap, deterministic *signals* with no LLM: tree-sitter
  structural facts per area (recurring imports, decorators, error-handling
  shapes, naming, base classes) and git signals (reverts, repeated churn on the
  same area, "fix"/"refactor" messages, the *why* in commit bodies). Then group
  signals by scope and feed bounded, focused context to the LLM with an editable
  prompt, asking for candidate priors as structured JSON validated against the
  schema. *Pro:* controls token cost, gives the model focused context, easier to
  debug. *Con:* signal collection is upfront work.

- **(B) Raw-feed.** Chunk files/diffs and ask the LLM to emit priors directly.
  *Pro:* simplest to build. *Con:* costly, noisy, little control over relevance —
  works against validating "are these *useful*."

- **(C) Heuristic-only, no LLM.** Rejected: the brief explicitly wants LLM
  extraction/summarization, and heuristics alone won't capture rationale.

**Recommendation: (A).** It directly serves the milestone question (useful, not
just abundant) and keeps cost/observability under control.

Pipeline: `pipeline.py` walks the repo → `signals.py` builds per-scope signal
bundles → `extractor.py` renders an editable prompt and calls the provider →
output JSON is validated into `Prior` records (status `candidate`, origin
`bootstrap`, with `source_refs` populated) → persisted via `PriorStore`.

Prompts live as plain-text files under `extraction/prompts/` with `{placeholder}`
substitution — no templating dependency — so they're trivial to inspect and edit.

## Serve over MCP

MCP server (official SDK), **stdio transport** for local agent integration.

- `get_priors_for_context(file_path_or_area: str, task_description: str)` →
  returns relevant **canonical** priors as compact structured context. v1
  relevance: filter by `scope` match against the path/area, then rank by simple
  keyword overlap with `task_description` and confidence. (Embeddings/vector
  search noted as a future door, not built — YAGNI.)
- `submit_candidate_learning(pattern, scope, rationale, source_refs, ...)` →
  stores a new prior as `status=candidate, origin=agent_submitted`, returns its
  id. Does **not** enter the canonical set.

## Curate (minimal CLI)

- `metatron ingest <repo_path>` — run the bootstrap pipeline.
- `metatron serve` — start the MCP server.
- `metatron candidates list [--scope ...]` — show candidate priors.
- `metatron candidates approve <id>` / `metatron candidates reject <id>` —
  human-in-the-loop promotion. Approve sets `canonical`; reject sets `rejected`.

## Testing

pytest throughout, each PR ships tests. Storage and extraction tested against the
`PriorStore` ABC and a faked `LLMProvider` (no network in tests). Parsing/gitlog
tested against tiny synthetic repos created in fixtures. The real target repo is
used only for manual end-to-end validation, never committed.

## Proposed PR sequence (small, reviewable, each with tests)

1. **Models + storage interface + SQLite store** — schema, `PriorStore` ABC,
   `SQLitePriorStore`, round-trip tests.
2. **Parsing + gitlog signal collection** — `LanguageParser` ABC, reference
   grammar, git reader, `signals.py`; tests on synthetic repos.
3. **Extraction** — `LLMProvider` ABC + `AnthropicProvider`, editable prompts,
   `extractor.py`, `pipeline.py`; tests with a fake provider.
4. **MCP server** — the two tools over stdio; tests.
5. **Curation CLI** — ingest/serve/candidates commands; tests. README updated to
   the full ingest → serve → curate walkthrough.

## Resolved decisions

These were the open questions; resolved as follows for milestone 1.

1. **Confidence:** enum `low | medium | high`. Human-legible for curation and
   avoids false precision from an LLM-generated float. Door stays open to add a
   numeric score later without breaking the API.
2. **Git history depth:** configurable, with a **bounded default** — most recent
   500 commits (`--max-commits`), plus an optional `--since <date>`. Bounded by
   default keeps the first ingest fast and cheap; flags expand to full history.
3. **Reference grammar:** **Python** is the reference grammar wired now (common
   case and enough to run the slice end-to-end). If the provided target repo is a
   different language, its grammar is added to the registry in the parsing PR —
   the language-agnostic abstraction makes that a drop-in.
4. **Retrieval in `get_priors_for_context`:** v1 = deterministic **scope match +
   keyword/confidence ranking**. Embeddings / vector search are a noted future
   door, not built (YAGNI).
5. **Serving:** `get_priors_for_context` returns **canonical priors only**.
   Consistent with the curation principle — uncurated candidates never reach an
   agent through the serve path.
6. **Config:** secrets via env (`ANTHROPIC_API_KEY`); non-secret settings
   (provider, model, db path, history caps) via a committed `metatron.toml`, with
   env vars overriding file values. `metatron.toml` holds no secrets, so it is
   safe to commit.
