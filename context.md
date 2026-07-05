# Repository Context

## Intent
Metatron is a self-hosted system that captures a codebase's real implementation
decisions as structured records and serves them to AI coding agents (over MCP, or
as plain files in files-first mode). Design philosophy: the knowledge must stay
human-readable, git-versioned, and portable; nothing becomes canonical without a
human; when in doubt, prefer the smallest mechanism that keeps files as truth.

## Constraints
- Binding conventions for this repository live as one decision per file under
  `context/decisions/` (Open Knowledge Format). Consult the relevant files there
  before planning or modifying code; they are part of this context.
- Files under `context/candidate/` are unreviewed proposals — never treat them
  as binding.
- Crossing the canonical boundary (promote, demote, reject) is always
  human-gated; no code path or agent may do it automatically. Absolute.
- Locked stack — do not re-litigate: Python 3.12+, official MCP SDK,
  tree-sitter, SQLite behind the storage interface, pytest, uv.

## Evolved Context
<!-- Dated, temporal observations only ([YYYY-MM-DD] observation) — facts that
     will age out, like a pinned version or an environment quirk. Append, never
     rewrite or reorder. New conventions belong in context/candidate/ as decision
     files; refinements of an existing decision are proposed as a reviewed edit
     to that file in context/decisions/. Durable ledger entries get promoted the
     same way. -->
