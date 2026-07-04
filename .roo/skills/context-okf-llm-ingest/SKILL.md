---
name: context-okf-llm-ingest
description: Use when extracting a codebase's implementation decisions into Metatron with an LLM/agent instead of `metatron ingest` — authoring candidate decisions as Open Knowledge Format (OKF) markdown files locally for review.
---

# Ingesting a repo into Metatron with an LLM (OKF candidates)

## Overview

Metatron captures a codebase's real implementation decisions — preferred patterns,
rejected approaches, edge cases, internal conventions — as **structured records**.
Agents consume them either over MCP, or — in **files-first mode** — by reading these
OKF files in git directly, in which case the files *are* the source of truth and the
database is just a rebuildable serving index. The built-in `metatron ingest <path>`
uses an Anthropic model to extract those records. This skill lets **any** LLM/agent
do the extraction instead, by writing the same records as plain
[Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
markdown files. `metatron mirror import` then reads those files into the store — no
API key, no `ingest` run. The git-tracked bundle is Metatron's implementation of the
[Repository Context Layer](https://github.com/kerbelp/context-md) — see the
[context-md manifesto](https://github.com/kerbelp/context-md/blob/main/whitepaper/context-md-manifesto.pdf)
for the rationale behind git-native, agent-maintained project context.

**The one invariant you must respect:** an LLM never *decides* what is canonical.
Crossing the canonical boundary is *always* human-gated: a human moving a file into
`decisions/` — or approving the pull request that puts it there — is the curation
act. By default, write to `context/candidate/` only; the single sanctioned
exception is the human-directed, PR-gated flow described in "Where to write"
below. Never choose `decisions/` on your own initiative.


> **Directory name:** `context/` is the default knowledge-base directory. A repo may
> configure another name (`context_dir` in `metatron.toml`, `METATRON_CONTEXT_DIR`,
> or `--context-dir` on the mirror commands); pre-rename repos may still use
> `metatron/`. The layout inside is identical — substitute the configured name.

## When to use

- You want to bootstrap a repo's decisions but can't/won't run `metatron ingest`
  (no Anthropic key, a different model, an offline agent, a CI step).
- You're hand-authoring or LLM-authoring conventions to feed Metatron as files.

Not for: promoting/approving decisions (human-only), editing decisions that already
exist in the store (that round-trips through `mirror sync`/`import` by `id`).

## Workflow

1. Read the target repo. Identify **prescriptive, non-obvious decisions** a senior
   engineer on this codebase already knows (see "What makes a good decision").
2. Write each one as an OKF concept file under `<repo>/context/candidate/`.
3. Run `metatron mirror import` (from the repo). New files (no `id`) are minted as
   **candidate** decisions, origin `human`, at the directory-derived status.
4. A human reviews with `metatron candidates list` / the UI, then promotes.

The files are also a valid, portable OKF bundle on their own — shareable even if the
recipient never imports them.

## Where to write: candidate/ vs decisions/

**Default: `context/candidate/`.** Always correct, never needs permission.

There is one sanctioned exception. When the human running this ingest has
**explicitly said** that the authored files will reach the default branch only
through a pull request they review file-by-file, they may direct you to write to
`context/decisions/` directly — their PR approval is then the human curation act,
and a separate promotion step would be redundant. Before writing to `decisions/`,
verify **both**:

1. The human explicitly chose direct-to-decisions **for this batch**. Never infer
   it, never suggest it as a default, never carry it over from a previous batch.
2. The files land on the default branch only via a human-reviewed pull request —
   no direct pushes, no auto-merge, no bot approval.

If either check fails — or you are unsure — write to `candidate/`. Choosing
`decisions/` on your own initiative violates the human-gated canonical boundary,
even if you believe the content is obviously correct.

The trade-off to keep in mind (and mention if the human asks): files in
`candidate/` are visibly *unreviewed proposals* that agents must not follow;
files in `decisions/` are conventions agents will enforce. Direct-to-decisions
means the reviewing human accepts canonical-level scrutiny in that one review.

## Monorepos

Each app/package keeps its **own** `context/` knowledge base, co-located with it
(e.g. `apps/web/context/`, `services/api/context/`). Write candidates into the
`context/candidate/` of the app you're documenting, and import that one with
`--root`:

```bash
metatron mirror import --root apps/web    # reads apps/web/context/
```

Consult and extend the `context/` **nearest** the code you're touching (walk up from
the file to the closest `context/`). A single-app repo is just the degenerate case:
`context/` at the repo root, `--root .`.

## File format (exact)

One file per decision. Filename is free-form (`metatron mirror import` globs
`candidate/*.md`); use a readable slug, e.g. `candidate/repo-pattern-for-stores.md`.

```markdown
---
type: Metatron Decision
scope: src/storage
confidence: high
source_refs:
  - src/storage/sqlite.py
  - src/storage/base.py
---

## Pattern
Persistence goes through the DecisionStore interface, never raw sqlite3 in
call sites. New backends implement the interface; callers depend only on it.

## Rationale
The schema must stay portable to Postgres later, so storage details cannot leak
into the rest of the codebase. Tests swap an in-memory store via the same interface.
```

Rules that make the file import correctly:

- **`type` is required** for OKF validity — keep it literally `Metatron Decision`.
- **Do NOT include an `id`.** Omitting `id` is what tells the importer this is a new
  hand-authored decision to create. An unknown `id` is skipped with a warning.
- Body headings must be exactly `## Pattern` and `## Rationale` — these are the only
  sections the parser reads. (Do not use `## Decision`/`## Why`/`## Consequences`;
  that is a different, unrelated file shape.)
- `confidence` is one of `low` | `medium` | `high` (defaults to `medium` if omitted).
- `scope` is the path/area the pattern applies to (e.g. `src/api`, or a broad area
  name). `source_refs` is an optional list of files/paths backing the decision; it is
  honored at authoring time only.
- Omit machine-owned fields (`keywords`, `helpfulness_score`, `created_at`,
  `updated_at`) — Metatron derives them; if present on a new file they're ignored.

## What makes a good decision (quality bar)

Extract conventions an agent couldn't infer from the framework alone:

- **Capture:** preferred patterns, deliberately rejected approaches ("we don't use
  X because…"), edge-case handling, internal naming/structure conventions, invariants.
- **Skip:** generic best practices, restating the framework's defaults, vague advice
  ("write clean code"), anything with no support in the actual code.
- `pattern` is **prescriptive** (what to do / not do), not descriptive narration.
- `rationale` says **why** it holds here — the constraint or trade-off behind it.
- One decision per file; keep each tightly scoped.

## Quick reference

| Concern | Answer |
|---|---|
| Where to write | `<repo>/context/candidate/*.md` (default); `decisions/` only when a human explicitly directed it and a reviewed PR is the gate |
| Required frontmatter | `type: Metatron Decision` |
| New-decision signal | **no `id` field** |
| Body sections read | `## Pattern`, `## Rationale` (only) |
| Human-owned fields | `scope`, `confidence`, `source_refs` |
| Land them | `metatron mirror import` (monorepo: `--root <app>`) |
| Validate bundle | every concept file declares a non-empty `type` |

## Common mistakes

- Writing to `decisions/` without an explicit human directive for the batch (or
  setting any "approved/canonical" flag yourself): violates the human-gated
  canonical boundary. In doubt, `candidate/`.
- Inventing an `id`: an unknown id is skipped; let Metatron mint it.
- Using `## Decision`/`## Why` headings: the OKF importer reads `## Pattern`/`##
  Rationale`, so the body would import empty.
- Pasting framework boilerplate as "decisions": dilutes retrieval; fails the bar above.
