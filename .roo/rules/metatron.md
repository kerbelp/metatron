# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `metatron/`: `metatron/decisions/` is **canonical**, `metatron/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `metatron/` — use the
one **nearest** the files you are touching (walk up to the closest `metatron/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `metatron/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `metatron/candidate/` (skill:
  `okf-llm-ingest`). Candidates are proposals for human review — never canonical.
- **Never self-promote.** Do not move files into `metatron/decisions/`. Promotion is
  human-gated: a person `git mv`s the file in a reviewed pull request (skill:
  `okf-promote-candidates`). Nothing self-promotes.
