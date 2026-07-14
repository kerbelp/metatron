# Review gate: where humans review agent-authored decisions

**Date:** 2026-07-14 · **Status:** shipped

## Problem

Files-first onboarding hard-coded the candidates-first workflow: agents author
proposals under `candidate/`, and a human later promotes them with a reviewed
`git mv`. For teams whose repositories already require pull-request review for
every change, this is a second, parallel review system: the PR that could have
carried the decision file is followed by another PR that moves it one directory.
The staging area's real value in such repos is tidiness (keeping decision diffs
out of feature PRs), not safety — the safety comes from the PR review either way.

## Decision

`metatron context setup` gains a `--review-gate` choice, persisted to
`metatron.toml` as `review_gate`:

- **`pr` (default).** Agents author OKF decision files directly under
  `decisions/` on a working branch. The human-reviewed pull request that lands
  them is the curation act. The context layer inherits whatever review
  discipline the repository already has.
- **`candidates`.** The previous behavior: proposals staged under `candidate/`,
  promotion as a separate reviewed `git mv`. For teams that want decision
  changes reviewed separately, or for setups where agents can reach the default
  branch without review — there the staging area is the only human checkpoint.

The core invariant is unchanged in both modes: **crossing the canonical boundary
is always human-gated** (CLAUDE.md, Core principle). A human approving the pull
request that adds a file to `decisions/` is the same curation act as a human
running the `git mv` — the gate setting only chooses where that review happens.
This was already the documented position ("a human placing or moving a file into
`decisions/` — or approving the pull request that does — is the curation act")
and the `context-okf-llm-ingest` skill already sanctioned per-batch
direct-to-decisions under explicit human direction; the setting makes that
direction a standing, configured repo policy instead of a per-batch conversation.

## Mechanics

- The gate resolves flag → `METATRON_REVIEW_GATE` env → `metatron.toml` →
  default `pr`, and the resolved value is written back to the workspace-root
  `metatron.toml`, so a repo's gate is always explicit after onboarding and
  every later run agrees with the generated contract.
- All gate-dependent artifacts are **managed and refreshed**: the `.roo/rules`
  rule, the installed skill copies (a `pr` repo gets a standing-policy note
  injected after the ingest skill's frontmatter), the KB README (recognized by
  its managed header; a hand-replaced README is never overwritten), and the
  `AGENTS.md` METATRON block (replaced between markers; surrounding content
  untouched). Re-running setup with the other gate flips the whole contract in
  one command.
- `context.md` is scaffolded with gate-appropriate wording but, as before, an
  existing file is never modified.
- Existing onboarded repos are unaffected until setup is re-run: no artifact is
  rewritten outside a `metatron context setup` invocation. A re-run without the
  flag keeps a previously persisted gate; only repos with no persisted value
  get the new `pr` default.

## Notes for fully autonomous deployments

With no human review anywhere (no PR gate, agents push to the default branch),
`pr` mode degrades to no review at all — exactly as it does for code. Such
deployments should use `candidates` mode and treat promotion as their one human
checkpoint, and run `metatron files lint` in CI so malformed decisions cannot
land silently.
