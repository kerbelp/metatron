---
type: Metatron Decision
scope: metatron/mirror
confidence: high
source_refs:
  - metatron/mirror/sync_import.py
  - metatron/filesfirst/schema.py
---

## Pattern
Anything that reads the knowledge-base status directories must skip the
reserved generated filenames (`RESERVED_FILENAMES` in `filesfirst/schema.py`:
`index.md`, `log.md`) and must not create a decision from an id-less document
unless it declares a non-empty `type` frontmatter field. Untyped strays are
skipped with a warning, never imported.

## Rationale
`files index` writes a generated listing into `decisions/`; an importer that
globs `*.md` naively turned it into an empty decision at CANONICAL status with
no human involved — a direct violation of the human-gated canonical boundary.
Requiring the OKF `type` declaration makes intent explicit and keeps stray
notes from silently becoming conventions.
