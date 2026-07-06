---
type: Metatron Decision
scope: metatron/repo_identity.py
confidence: high
source_refs:
  - metatron/repo_identity.py
  - metatron/storage/catalog.py
---

## Pattern
A repo's identity is the normalized `origin` remote (`host/path`, no scheme,
no user, no `.git`), falling back to the directory name only when there is no
remote. Never key anything on the local checkout path. Derived artifacts follow
the same rule: per-repo database files carry a self-describing `repo_meta` row,
so the filename is only a readable handle, never the source of truth.

## Rationale
Identity must be constant across developers, machines, and checkout locations —
the same repo cloned to two paths is one repo. Self-describing DB files survive
being renamed or handed off.
