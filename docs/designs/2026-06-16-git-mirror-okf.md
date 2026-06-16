# Design: git-backed decision mirror + Open Knowledge Format export

- **Date:** 2026-06-16
- **Status:** draft
- **Surface:** new `metatron mirror sync` / `metatron mirror import` CLI commands, a new
  exporter/importer module, and a git-tracked directory inside the consuming
  repo (`metatron/candidate/`, `metatron/decisions/`). SQLite storage and the
  curation web UI are unchanged in behavior.

## Goal

Make the candidate→canonical lifecycle **auditable in git** and **editable as
files**, so a human (or the LLM they work through) can read, diff, review, and
author decisions without the web UI — while the SQLite database stays the single
source of truth for everything machine-derived. The same files are emitted as a
valid **Open Knowledge Format (OKF)** bundle, which doubles as a public,
promotable artifact.

Two user needs drive this, and they are deliberately kept distinct:

1. **Auditability** — today the lifecycle lives only in SQLite; there is no
   history, diff, blame, or review trail for "what became canonical, when, by
   whom, and why."
2. **File-first editing** — people increasingly prefer working through an LLM
   over plain files rather than a bespoke UI. Decisions-as-files gives them a
   first-class, UI-free editing surface.

## The line we hold

- **SQLite remains authoritative.** Retrieval, the LLM `keywords` field, and
  feedback scoring are untouched. The git directory is a *synced mirror*, never a
  parallel database.
- **Nothing crosses the canonical boundary without an explicit human action.**
  Here the act of a human writing or moving a file into `decisions/` *is* that
  action (see Directory-as-status). No machine path writes straight to canonical.
- **Machine-derived fields never round-trip.** The helpfulness score (computed by
  `feedback_score.py`), `keywords`, and timestamps are computed by Metatron; the
  mirror shows them read-only and import ignores any human change to them.
  `confidence` is a human-set enum (`low`/`medium`/`high`) and *is* round-tripped.

## Architecture overview

```
            metatron mirror sync  (DB -> files)
   SQLite  ───────────────────────────────►  metatron/candidate/*.md
 (source of                                   metatron/decisions/*.md
   truth)   ◄───────────────────────────────  (git-tracked mirror = OKF bundle)
            metatron mirror import (files -> DB)
```

- **Export (`metatron mirror sync`)** is the steady-state direction: it writes the
  current DB state out to the mirror so the audit trail (and OKF bundle) is
  always current. Safe to run any time; deterministic output.
- **Import (`metatron mirror import`)** is the human-edit direction: it reads the mirror
  back, applies human-owned changes, and shows a diff. Status is taken from the
  directory the file lives in.
- Both directions are **explicit commands** in v1. An automatic watcher / MCP
  auto-export is explicitly out of scope (see Future work).

## Directory-as-status

The directory a file lives in *is* its `status`:

```
metatron/
  candidate/
    use-zod-for-validation.md     # status = candidate
  decisions/
    repo-layout-is-monorepo.md    # status = canonical
```

- A human placing or moving a file into `decisions/` is the explicit human
  approval that promotes a candidate to canonical. Promotion is therefore a
  `git mv metatron/candidate/foo.md metatron/decisions/foo.md` — a reviewable,
  blameable git operation that preserves file history across the status change.
- `rejected` decisions are **not** mirrored as editable files (mirroring them
  would invite re-authoring rejected content as canonical by moving a file).
  Rejection stays a UI/DB action; the audit of rejections is out of scope for v1
  and noted in Open questions.

### Identity & filenames

- Filename is a **stable slug derived from the decision's DB identity**, not its
  content, so editing the body does not orphan git history and a promotion is a
  clean rename rather than a delete+create.
- The frontmatter carries the canonical decision id as the durable key; the slug
  is for human/git readability. Import matches on the id, falling back to slug for
  brand-new human-authored files that have no id yet.

## File format

One markdown file per decision: YAML frontmatter envelope + markdown body. This
is the OKF *pattern* (a directory of markdown + frontmatter), with Metatron's own
decision ontology inside it — we do **not** adopt OKF's data-analytics document
types.

```markdown
---
# --- human-owned (file wins on import) ---
id: dec_01HZ...            # durable identity; do not edit
scope: web/api
confidence: medium         # human-set enum: low | medium | high
source_refs:
  - src/api/validate.ts:42
# --- machine-owned (read-only; DB wins; import ignores edits here) ---
helpfulness_score: 0.91    # derived by feedback_score.py; rendered for audit only
keywords: [validation, zod, schema]
created_at: 2026-06-02T10:11:00Z
updated_at: 2026-06-14T09:03:00Z
---

## Pattern
Use `zod` schemas at API boundaries; never hand-roll request validation.

## Rationale
... (human-owned prose) ...

<!-- feedback: read-only, regenerated by `metatron mirror sync` -->
## Feedback summary
score 0.91 · 14 helpful / 1 unhelpful · last updated 2026-06-14
- "matched our boundary-validation convention on first try"
- "caught a hand-rolled validator in review"
```

### Field ownership

| Field | Owner | On `import` |
|-------|-------|-------------|
| `pattern` (body) | human | file wins |
| `scope` | human | file wins |
| `rationale` (body) | human | file wins |
| `source_refs` | human (authoring only) | honored on a new hand-authored file; read-only on edit |
| `confidence` (enum) | human | file wins |
| `status` (= directory) | human | directory wins |
| `helpfulness_score` | machine | ignored (warn if changed) |
| `keywords` | machine | ignored (warn if changed) |
| `created_at` / `updated_at` | machine | ignored |

> Note: `source_refs` is honored when a human authors a brand-new file (no `id`) but
> is **not** round-tripped on edits to existing decisions — the storage layer has no
> `update_fields` path for it yet, so it renders read-only and is excluded from the
> change fingerprint. Full source-ref editing is deferred.
>
> Note: `confidence` is the curator's `low`/`medium`/`high` enum (editable today in
> the web UI via `update_fields`), distinct from the machine-derived
> `helpfulness_score` that `feedback_score.py` computes from agent ratings. Only the
> latter is read-only in the mirror.

## Feedback in the mirror

Feedback is a high-volume, mostly agent-generated stream; mirroring raw events
would bury the signal in churny diffs. Instead each decision file carries a
**read-only rolled-up summary block** — score, helpful/unhelpful counts, and the
last N feedback rationales — regenerated on every `metatron mirror sync`. The raw
feedback stream and the computed score stay DB-owned and never import back. The
audit answers "*why did this decision's confidence move?*" without becoming a log
dump.

## Sync mechanics & collision handling

- **`metatron mirror sync`** — full deterministic export of all `candidate` and
  `canonical` decisions to the mirror. Idempotent: re-running with no DB change
  produces no diff.
- **`metatron mirror import`** — reads the mirror, computes per-decision diffs against
  the DB on human-owned fields only, and applies them. Status is set from the
  file's directory. Output is a human-readable diff of what changed.
- **Collision** — the accepted risk of two-way sync: a human edits a file *and*
  the DB changed the same human-owned field since the last `sync`. Import does
  **not** silently clobber; it surfaces the conflicting decision and leaves it for
  the human to resolve (re-`sync` to take DB, or re-edit the file to take theirs).
  Detection uses a per-decision last-synced marker (content hash) recorded at
  `sync` time.

## OKF export (shipped feature)

The mirror **is** the OKF bundle: the same markdown+frontmatter files, laid out to
satisfy OKF v0.1's bundle structure (manifest + documents), so the directory is a
valid OKF bundle with no separate build step.

- Metatron's decision fields map onto OKF's frontmatter envelope; our ontology
  stays ours, the *container* is OKF-shaped.
- `metatron mirror sync --okf` (or an equivalent export flag) writes/validates the
  bundle against OKF v0.1.
- **Public surface:** documented in the public README and on the website as
  first-class OKF support; a natural fit for a getmetatron.com/blog product post.
  All public copy stays neutral and product-focused.
- We do **not** build Metatron *on top of* OKF v0.1 (4-day-old, single-vendor,
  data-analytics-oriented). OKF is an export target and a layout pattern, not the
  core data model.

## Components

- **`metatron/mirror/export.py`** — DB → markdown bundle; deterministic
  rendering; writes the read-only feedback summary and last-synced hash markers.
- **`metatron/mirror/import.py`** — markdown bundle → DB; directory→status;
  human-owned field diffing; collision detection; machine-field guard.
- **`metatron/mirror/okf.py`** — OKF bundle manifest/layout + v0.1 validation,
  built on the same rendered documents as `export`.
- **`metatron/cli.py`** — a `mirror` subcommand group (`mirror sync` / `mirror
  import`, with `--okf`), following the existing `repo` / `candidates` grouping.
  Distinct from the existing top-level `export` / `import` (DB-catalog transfer).
- Reuses existing `storage/` (read/write decisions) and the feedback rollup that
  already backs the UI's feedback summary.

## Testing

- **Round-trip:** `sync` then `import` with no edits is a no-op (no DB change, no
  file diff).
- **Promotion:** moving a file candidate/→decisions/ and `import` flips status to
  canonical and nothing else.
- **Field guard:** editing a machine-owned field in a file is ignored on import
  and warns; human-owned edits apply.
- **Collision:** concurrent DB + file edit to the same human field is reported,
  not clobbered.
- **OKF validity:** exported bundle passes OKF v0.1 structural validation.
- **Determinism:** repeated `sync` produces byte-identical output for unchanged
  data.

## Future work (out of scope for v1)

- Auto-sync: a watcher and/or MCP-server auto-export on write, so files stay
  current without running CLI commands.
- Audit/mirroring of `rejected` decisions.
- Bidirectional auto-merge (three-way) instead of explicit collision surfacing.

## Open questions

- Exact OKF v0.1 manifest requirements and how strictly to validate at export.
- Whether the feedback summary's "last N" count is configurable or fixed.
- Rejected-decision auditability (deferred): is a git audit of rejections wanted
  later, and in what form?
