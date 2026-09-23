---
type: Metatron Decision
scope: metatron/filesfirst
confidence: high
source_refs:
  - metatron/filesfirst/document.py
  - metatron/filesfirst/lint.py
  - metatron/filesfirst/index.py
---

## Pattern
Use a concise, topic-bearing slug for every Git-tracked decision filename. Keep
an opaque durable id, when one exists, in frontmatter independently of the
filename. Generated indexes link the readable filename while retaining the id
for ledger and integration references.

## Rationale
The Git tree is the files-first navigation and retrieval surface. UUID filenames
hide the decision topic from humans, agents, shell tools, and diffs. Separating
identity from presentation permits readable renames without breaking durable
references.
