---
name: context-okf-llm-ingest
description: Use when extracting a codebase's implementation decisions with an LLM/agent into Open Knowledge Format (OKF) files, following the repository's configured PR or candidate review gate.
---

# Authoring repository decisions with an LLM

## Overview

Capture a codebase's real implementation decisions — preferred patterns, rejected
approaches, edge cases, internal conventions — as structured OKF markdown files.
Any coding agent can author them; `metatron ingest` is not required.

In **files-first mode**, agents read the Git-tracked files directly. No database,
MCP server, or import is needed. The files are a portable
[Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
bundle and implement the
[Repository Context Layer](https://github.com/kerbelp/context-md).

**Human review is the canonical boundary.** Follow the repository's configured
review gate: either a human-reviewed PR containing decision files, or separate
review of staged candidates. Authoring on a branch is not permission to merge.

> **Directory name:** `context/` is the default knowledge-base directory. Honor
> the configured `context_dir` in `metatron.toml` or `METATRON_CONTEXT_DIR`;
> pre-rename repos may still use `metatron/`. Substitute the resolved directory
> in all paths and commands below. In monorepos use the knowledge base nearest
> the code, such as `apps/web/context/`, and the workspace's installed skills.

## Workflow (files-first)

1. Read the repository instructions, `context.md`, and relevant existing decisions
   before exploring implementation details. Check the review gate below.
2. Inspect source and tests. Extract **prescriptive, non-obvious conventions**
   supported by that evidence, rather than generic framework advice.
3. Write one OKF file per new convention in the gate's destination directory.
   Amend an existing decision when it already covers the same convention.
4. Validate the destination with `metatron files lint --path context/decisions`
   for the PR gate, or `metatron files lint --path context/candidate` for staging.
5. Inspect `git status --short` and the complete diff. New untracked files need
   their own view, e.g. `git diff --no-index -- /dev/null context/decisions/repo-pattern-for-stores.md`
   (exit 1 means differences). Include the decision changes in the human-reviewed
   PR, or present the staged candidates for human selection. Stop before merging
   or promoting anything without the required human review.

The files are ready for Git review at this point. Do not run `mirror import`,
`candidates list`, or start a database/UI as part of this files-first workflow.

## Where to write: follow the review gate

Read `review_gate` in the repository configuration and its generated instructions.
`metatron context setup` defaults to **`pr`** and persists the selected gate.

- **`pr`:** write directly to `context/decisions/` **on a working branch**.
  This is standing repository policy; no separate per-batch permission or
  candidate promotion is needed. A human reviews the decision diff in the PR
  before it reaches the default branch. Never push decisions directly there,
  auto-merge, or substitute bot approval for human review. `context/candidate/`
  remains optional staging for proposals not yet ready for PR review.
- **`candidates`:** write new proposals to `context/candidate/`. They are
  unreviewed and must not be treated as authoritative. A human selects the files
  to move to `context/decisions/`; use `context-okf-promote-candidates` for those
  explicitly selected moves in a reviewed PR.
- **No established gate, conflicting instructions, or no reviewed branch:** use
  `context/candidate/` and surface the missing review policy. Do not infer that
  writing directly to the default branch is allowed.

## New convention, amendment, or observation?

- **New convention:** author a new file in the destination selected above.
- **Refinement of an existing decision:** propose an edit to that decision on a
  working branch for human PR review. Constraints are edited, not appended;
  do not create an overlapping candidate that a human must reconcile later.
  If a reviewed branch is unavailable, present the proposed diff for review.
- **Dated, temporal observation:** append a `[YYYY-MM-DD]` entry to
  `## Evolved Context` in the root `context.md`. A pinned version or temporary
  proxy failure is not a durable convention. Follow normal repository review.

## File format

Use one readable slug per decision, e.g. `repo-pattern-for-stores.md`, in the
selected directory. This example is valid for either review gate:

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

- Keep `type: Metatron Decision` and the exact headings `## Pattern` and
  `## Rationale`; other heading names do not populate those parsed fields.
- New hand-authored files do not need an `id`. Preserve an existing ID when editing.
- `confidence` is `low`, `medium`, or `high`; `scope` names the applicable path/area.
- Include supporting file paths in `source_refs` when available.
- Omit machine-owned fields such as `helpfulness_score`, `created_at`, and
  `updated_at`. Directory placement expresses status; do not declare a proposal
  approved through frontmatter.

## Quality bar

- Capture conventions an agent could not infer from the framework alone:
  preferred patterns, documented rejected approaches, edge cases, naming rules,
  and invariants supported by the repository.
- The pattern is **prescriptive** (what to do); the rationale explains **why here**.
  Distinguish observed behavior from inferred rationale. Do not invent historical
  incidents or undocumented design intent.
- Skip generic best practices, vague advice, and unsupported claims.
- Keep each decision tightly scoped; consult existing decisions before adding one.

## Optional: database-backed MCP workflow

Use this section only when the user is actually maintaining a Metatron store for
MCP or database-backed curation. It is unnecessary for Git/files-first use.

In that workflow, `metatron mirror import` reads the configured bundle into the
store; for an app-local bundle use `metatron mirror import --root apps/web`.
New files without IDs are created at their directory-derived status. Do not
invent IDs: unknown IDs are skipped by the importer. Existing content edits
round-trip through `mirror sync`/`import`; `source_refs` is honored when creating
a record. Database candidates are reviewed through `metatron candidates list`
or the curation UI and approved by a human. Import is not a substitute for that
review: never place an unreviewed proposal in `decisions/` to bypass it.
