# Design: employee attribution (who used Metatron / gave feedback)

- **Date:** 2026-06-06
- **Status:** approved (owner brainstorming)
- **Motivation:** Metatron serves agents across an organization. We want to know
  *which employee's* agent ran a query / submitted a learning / gave feedback, and
  show that in the UI — so a curator can see who contributed what.

## Decisions (and what we deliberately are NOT doing)

- **Local identity, not an auth server.** CLAUDE.md defers auth / multi-tenant / RBAC /
  hosted app. We add a *local* identity (a config file), seeded from `git config`. No
  network registration, no login. This is metadata about the person running Metatron,
  not access control.
- **The server stamps identity; the agent never sends it.** Identity belongs to the
  person running `metatron serve`, not to the coding agent. `serve` reads the local
  identity once and stamps it onto every event it records. The agent does nothing — no
  tool-param changes, no MCP-URL query param (serve is **stdio**; there is no URL), and
  nothing the agent can forget or spoof.
- **Attribution is denormalized onto the immutable event.** Each event carries
  `actor_id` / `actor_email` / `actor_name`. So a handed-off or merged DB stays
  self-describing (same philosophy as `repo_meta`) — identity travels with the data and
  needs no central actor table.
- **Deployment model = local + export/merge to a curator.** Employees run Metatron
  locally; per-repo DBs are exported (existing `export`) and **merged** by a curator.
  Attribution becomes visible after merge, so this work also adds a minimal
  `metatron import`.

## Components

### 1. Identity (`metatron/identity.py`)
- `Identity(BaseModel)`: `actor_id: str = ""`, `email: str = ""`, `display_name: str = ""`.
  Empty = anonymous (backward-compatible; pre-existing events have no actor).
- Config file: `<METATRON_HOME>/config.toml`, default `~/.metatron/config.toml`
  (`METATRON_HOME` env overrides — also how tests isolate it). Distinct from the cwd
  project `metatron.toml`. Shape:
  ```toml
  [identity]
  actor_id     = "a3f1c2…"            # stable; sha1(email)[:12], else a uuid
  email        = "kerbelp@gmail.com"
  display_name = "Pavel Kerbel"
  ```
- `load_identity() -> Identity` — pure read; returns empty Identity if no file.
- `ensure_identity() -> Identity` — load; if empty, seed from `git config user.email` /
  `user.name`, write the file, return it. Called by `serve` (zero-friction first run).
- `set_identity(*, email=None, display_name=None) -> Identity` — write/update the file
  (recomputes `actor_id` from email when email changes).

### 2. Event fields + stamping
- `metatron/events.py`: add `actor_id` / `actor_email` / `actor_name` (str, default "").
- `metatron/storage/sqlite.py`: add the three columns to the events schema +
  `_ensure_column` for older DBs; include them in `_EVENT_COLUMNS`.
- `metatron/mcp_server/server.py`: `build_server(..., identity: Identity | None = None)`;
  the internal `_record(event)` stamps the actor fields onto the event (when present)
  before persisting. Covers all three event kinds (query/submit/feedback).
- `metatron/cli.py`: `serve` resolves `ensure_identity()` and passes it to `build_server`.

### 3. CLI: `metatron whoami`
- `metatron whoami` prints the current identity (and the config path).
- `metatron whoami --set-email … --set-name …` updates it.
- On a fresh machine `whoami` (like `serve`) seeds from git if unset.

### 4. UI/API exposure
- `usage.recent_queries` / `recent_submissions` already `model_dump` events → actor
  fields appear automatically once on the model.
- `feedback_events` builds explicit dicts → add `actor_id` / `actor_email` /
  `actor_name` to each event dict (`api.py`).
- (Stretch, optional) a "top contributors" rollup — deferred unless trivial.
- The new UI (being designed) should display the actor on the feedback + activity
  streams; the data contract now carries it.

### 5. Merge: `metatron import <file>`
- `metatron/storage/transfer.py`: `copy_repo_rows(src_priors, src_events, src_runs,
  dst, repo) -> dict` — insert rows whose ids aren't already in `dst` (dedupe by id),
  returns per-kind counts. Refactor `migrate_legacy_db` to use it (DRY with the
  crash-idempotent copy we just wrote).
- `import_catalog(src: Catalog, dst: Catalog) -> dict` — for each repo in `src`, copy
  into `dst`. `src` may be a single-file hand-off DB or another catalog dir.
- `metatron/cli.py`: `metatron import <path>` opens `<path>` as a `Catalog` (single-file
  or dir), merges into the active catalog, prints a per-repo summary. Idempotent
  (re-importing the same file is a no-op).

## Privacy note
`email` is mild PII, stored locally in an internal tool, never transmitted by Metatron
itself (it only travels if the owner exports/shares a DB). Acceptable for the intended
org-internal use; documented so it's a conscious choice.

## Build order (small PRs, each with tests)
1. **Identity module + `whoami`** — `identity.py`, git-seeding, config read/write, CLI
   `whoami`. Test isolation via `METATRON_HOME` (extend the autouse conftest fixture).
2. **Event actor fields + serve stamping** — `events.py`, sqlite columns,
   `build_server(identity=…)`, `serve` wiring.
3. **API/UI exposure** — actor fields in `feedback_events`; confirm `usage` carries them.
4. **`transfer.copy_repo_rows` + `metatron import`** — refactor `migrate` onto the shared
   primitive, add `import_catalog` + the CLI command.
```
