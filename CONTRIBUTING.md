# Contributing to Metatron

Thanks for your interest in Metatron! Metatron captures a codebase's real
engineering decisions as structured records and serves them to coding agents over
MCP. This guide covers how to set up, make a change, and get it merged.

Before you start, please skim two files — they define how this project thinks:

- **[README.md](README.md)** — what Metatron is and how to run it.
- **[CLAUDE.md](CLAUDE.md)** — the ground rules: the locked tech stack, the core
  curation invariant, and what is intentionally out of scope. Everything below
  defers to it.

## The two rules that aren't up for debate

These come from `CLAUDE.md` and a PR that breaks either will be sent back:

1. **Nothing enters the canonical set without human curation.** No decision
   self-promotes. Crossing the canonical boundary — promote, demote, reject — is
   always a human action. Don't add a code path that auto-approves, auto-rejects,
   or otherwise lets a decision become canonical on its own. (The bounded
   serve-ordering auto-weighting described in `CLAUDE.md` is the *only* automatic
   behavior, and it never crosses that boundary.)

2. **Stay inside the current scope.** Several things have deliberate doors left
   open but are **not to be built yet** — auth / multi-tenant / RBAC / a hosted
   web app, telemetry ingestion, ticket/postmortem ingestion, and Postgres (use
   SQLite behind the storage interface). See the "Scope discipline" section of
   `CLAUDE.md`. If you think one of these should change, open an issue first.

## Development setup

Metatron uses **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)** for all
tooling.

```bash
git clone https://github.com/kerbelp/metatron.git
cd metatron
uv sync                 # create the venv and install dependencies
uv run metatron --help  # sanity check
```

## Running the tests

```bash
uv run pytest           # the whole suite
uv run pytest -q        # quieter
uv run pytest tests/test_storage_concurrency.py -v   # a single file
```

The suite must be green before you open a PR.

## Making a change

We work **PR-then-merge**. There are **no direct commits to `main`**.

1. **Open an issue first** for anything non-trivial (a new feature, a behavior
   change, anything touching the curation boundary or scope). For small, obvious
   fixes a PR on its own is fine. This saves you from building something that
   would be declined on scope grounds.
2. **Branch** off `main` with a short descriptive name (e.g.
   `fix-ui-stale-reads`, `add-export-flag`).
3. **Keep the PR small and reviewable.** One logical change per PR. Large,
   multi-concern PRs are hard to review and slow to merge — split them.
4. **Include tests.** Every PR that changes behavior adds or updates tests. New
   behavior gets a test that fails before your change and passes after. Bug fixes
   get a regression test.
   - The web UI (`metatron/webui/app/`) is static JSX/CSS served via CDN Babel and
     has no JS test harness, so frontend-only changes can't carry automated tests —
     say so in the PR and describe how you checked it manually.
5. **Match the surrounding code.** Mirror the existing naming, structure, and
   comment density of the file you're editing rather than introducing a new style.
   Keep the storage layer behind its interface (it must stay portable to Postgres).
6. **Update the docs you touch.** If you add or change a CLI subcommand, update
   `README.md` (there's a test that checks every subcommand is documented). If you
   change behavior the docs describe, update the docs in the same PR.

## Commit and PR conventions

- Write commit messages and PR descriptions that explain **why**, not just what.
  If you're fixing a subtle bug, describe the root cause; the next person reading
  `git blame` should understand the change without re-deriving it.
- A short type prefix (`fix:`, `feat:`, `ui:`, `docs:`, `chore:`) in the subject
  is appreciated but not required.
- PRs are merged with **squash + delete branch**, so the PR title becomes the
  commit on `main` — make it a clear, self-contained summary.

## Reporting bugs

Open a GitHub issue with: what you expected, what happened, the exact command or
steps, and your OS / Python / Metatron version (`metatron --help` shows the
version). A minimal reproduction is the fastest path to a fix.

## Security issues

Metatron runs against private codebases, so treat security carefully. **Do not
open a public issue for a vulnerability.** Email **kerbelp@gmail.com** with the
details and we'll coordinate a fix and disclosure privately.

## License of contributions

Metatron is released under the [MIT License](LICENSE). By submitting a
contribution, you agree that it is licensed under those same terms (inbound =
outbound). A Contributor License Agreement may be introduced later; if so, this
section will be updated and the PR check will tell you what to do.
