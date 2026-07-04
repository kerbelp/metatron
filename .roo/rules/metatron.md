# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `context/`: `context/decisions/` is **canonical**, `context/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `context/` — use the
one **nearest** the files you are touching (walk up to the closest `context/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `context/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have. **Only `decisions/` is
  authoritative** — never treat `context/candidate/` content as a convention to
  follow; candidates are unreviewed proposals.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `context/candidate/` (skill:
  `context-okf-llm-ingest`). Candidates are proposals for human review — never canonical.
  Refining an *existing* decision? Propose an edit to that file in
  `context/decisions/` on a reviewed branch instead of authoring an overlapping
  candidate.
- **Never self-promote.** Do not move files into `context/decisions/`. Promotion is
  human-gated: a person `git mv`s the file in a reviewed pull request (skill:
  `context-okf-promote-candidates`). Nothing self-promotes.
