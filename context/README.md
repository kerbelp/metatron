# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — optional staging for proposals not yet ready for review.

This repo's review gate is `pr`: decisions are authored directly under
`decisions/` on a working branch, and the pull request that lands them is the
human curation act. Never merge decision changes to the default branch without
review. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
