# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `context/`: `context/decisions/` is **canonical**, `context/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `context/` — use the
one **nearest** the files you are touching (walk up to the closest `context/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `context/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `context/candidate/` (skill:
  `okf-llm-ingest`). Candidates are proposals for human review — never canonical.
- **Never self-promote.** Do not move files into `context/decisions/`. Promotion is
  human-gated: a person `git mv`s the file in a reviewed pull request (skill:
  `okf-promote-candidates`). Nothing self-promotes.
