---
type: Metatron Decision
scope: metatron/storage
confidence: high
source_refs:
  - metatron/storage/base.py
  - metatron/storage/sqlite.py
  - CLAUDE.md
---

## Pattern
All persistence goes through the `DecisionStore` / `EventStore` abstract
interfaces in `metatron/storage/base.py` — never raw `sqlite3` calls at call
sites. New backends implement the interface; callers depend only on it, and
implementations must not leak storage-specific details (SQL fragments, row
shapes, connection objects) to callers.

## Rationale
The schema must stay portable to Postgres later (a locked stack decision), so
storage details cannot spread through the codebase. The interface also lets
tests swap an in-memory SQLite store without touching call sites.
