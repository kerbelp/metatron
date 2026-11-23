---
type: Metatron Decision
scope: metatron
confidence: high
source_refs:
  - metatron/filesfirst/document.py
  - metatron/mirror/export.py
  - metatron/config.py
  - tests/test_text_encoding.py
---

## Pattern
Read and write Metatron's Markdown, TOML, JSON, and prompt files with an explicit
`encoding="utf-8"`. Decode source files for ingestion as UTF-8 too; retain the
existing skip behavior for undecodable or unreadable source files. Never depend
on the host locale for these text operations.

## Rationale
Files-first already writes UTF-8. Using locale defaults elsewhere makes the
same file incompatible across paths on Windows: mirror export can fail on an
em dash, while import, UI edits, configuration, and templates can fail to decode
or silently corrupt non-ASCII text. Tests simulate legacy Windows defaults so
these failures are visible even when CI runs on a UTF-8 host.
