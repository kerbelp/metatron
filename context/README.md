# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — **proposed** conventions awaiting human review.

Promotion is human-gated: a reviewer `git mv`s a file from `candidate/` to
`decisions/` in a pull request. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
