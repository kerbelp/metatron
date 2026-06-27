---
name: okf-promote-candidates
description: Use when promoting reviewed Metatron candidate decisions to canonical in a git/CI flow — moving Open Knowledge Format (OKF) files from candidate/ to decisions/. The agent performs only human-named moves; it never decides what to promote.
---

# Promoting candidates to canonical (OKF, git-as-truth)

## Overview

A Metatron decision becomes **canonical** by moving its OKF file from
`metatron/candidate/` to `metatron/decisions/`. The directory *is* the status.
This skill covers doing that move in a git/CI flow, as a companion to authoring
candidates (see the `okf-llm-ingest` skill).

**This skill is mechanical only.** You move the specific files a human named, and
nothing else. You do **not** decide which candidates are worthy — that judgment is
the human curation act Metatron's model is built around.

## The invariant — read before doing anything

Crossing the canonical boundary is **always human-gated**. Nothing self-promotes.
In a git flow, the gate is **a human approving the specific pull request** that
contains the `candidate/ → decisions/` move. That approval *is* the curation act.

So, absolutely:

- **Only move candidates a human explicitly named** (by id/slug, or as the agreed
  contents of the promotion PR). Never sweep "these look good."
- **Never auto-merge.** Do not promote on green CI, on a schedule, or via a bot that
  merges its own PR. CI may validate and rebuild the serving index; the **merge is a
  human's**.
- **Promotion is a pure move.** Do not edit `pattern`/`rationale`/`scope` in the same
  change — editing content is authoring, a separate act with its own review.
- **One promotion PR, kept legible.** Don't bury promotions inside a large authoring
  diff; a reviewer must be able to see exactly what is crossing the boundary.

If you are tempted to choose what to promote, stop — that is the human's job.

## Model: git is the source of truth

Files stay **id-less**; the directory (`candidate/` vs `decisions/`) is the status.
`metatron mirror import` rebuilds the serving database from the files — the DB is a
derived, rebuildable index, not something you curate or hand-edit. Do **not** stamp
`id` fields into files (an `id` the rebuilt DB doesn't know is skipped on import).

## Workflow

1. A human names the candidate(s) to promote (e.g. `metatron/candidate/use-repo-pattern.md`).
2. For each named file, move it — preserving history:
   ```bash
   git mv metatron/candidate/use-repo-pattern.md metatron/decisions/use-repo-pattern.md
   ```
3. Open a pull request with only those moves. A human reviews and **merges**.
4. After merge, reconcile the serving index (locally or in CI):
   ```bash
   metatron mirror import     # rebuilds the DB from files; moved files become canonical
   ```

**Monorepos:** each app has its own `metatron/` (e.g. `apps/web/metatron/`). Move the
file within that app's tree (`apps/web/metatron/candidate/X.md` →
`apps/web/metatron/decisions/X.md`) and reconcile it with
`metatron mirror import --root apps/web`.

## CI's allowed role

- **Validate** the bundle: every concept `.md` declares a non-empty `type`; `.md`
  files live only under `candidate/` or `decisions/`.
- **Rebuild** the serving index with `metatron mirror import` (it's derived).
- **Never merge on its own.** No promote-on-green, no auto-merge of promotion PRs.

## Quick reference

| Concern | Answer |
|---|---|
| What promotes a decision | `git mv` from `candidate/` to `decisions/` |
| Who chooses what to promote | A human (named explicitly) — never the agent |
| The human gate | Approval/merge of the specific promotion PR |
| After merge | `metatron mirror import` rebuilds the serving DB |
| Leave `id` out? | Yes — files stay id-less; an unknown id is skipped on import |
| Edit content while promoting? | No — promotion is a pure move |

## Common mistakes

- **Deciding worthiness.** Selecting candidates yourself, even "obvious" ones —
  that's the curation act; a human must name them.
- **Auto-merge / bot promotion.** Any path where files reach `decisions/` on `main`
  without a human approving that change violates the human-gated invariant.
- **Promoting in a big mixed PR.** Folding promotions into a large authoring diff so
  the curation can't be reviewed cleanly. Keep promotion PRs small and move-only.
- **Editing during the move.** Changing `pattern`/`rationale` in the promotion — do
  content edits as a separate authoring change.
- **Stamping `id`s.** Writing `id` into files; the rebuilt DB won't know it and the
  file is skipped on import.
- **Moving to a wrong path.** Files must land directly in `metatron/decisions/`; only
  `candidate/` and `decisions/` are status directories.
