# Design: per-repo database split (shippable single-repo DBs)

- **Date:** 2026-06-06
- **Status:** proposed (awaiting owner review)
- **Motivation:** make a single repo's priors a self-contained, hand-off-able
  artifact, so someone who doesn't want to set up MCP can be given one `.db` file
  and run `metatron` against it locally.

## Goal

Today all repos share one `metatron.db` with a `repo` column on every table. We
want **one SQLite file per repo**, so a repo's knowledge is a single portable file
you can send to a teammate or customer. The recipient installs `metatron` (no MCP
wiring) and points it at the file — `metatron --db received.db ui|serve|...`.

The CLI, MCP server, and local UI must keep working **seamlessly across multiple
repos**, exactly as they do today.

## Non-goals (line we hold)

- **No Postgres, no multi-tenant, no auth, no hosted app.** This stays a single-user,
  local, SQLite-behind-the-interface system (CLAUDE.md scope discipline). Per-repo
  files are still SQLite behind the existing `PriorStore`/`EventStore` interfaces.
- **No portable export format (Markdown/JSON) in this design.** The owner chose the
  "install metatron, point at file" hand-off model; the deliverable is the raw `.db`.
  A text export can be added later if a no-install path is wanted.
- **No change to the curation invariant.** Nothing here promotes, demotes, or
  auto-mutates priors across the canonical boundary.

## Background: how storage works today

- `metatron/config.py`: `Settings.db_path` (default `metatron.db`), overridable via
  `METATRON_DB` env or `metatron.toml`. One file path.
- `metatron/storage/sqlite.py`: `SQLitePriorStore`, `SQLiteEventStore`,
  `SQLiteIngestRunStore` each open that one path. Every table carries a `repo` column;
  reads filter by it. `list_repos()` is `SELECT DISTINCT repo FROM priors`.
- `metatron/cli.py`: `_resolve_repo(explicit, store, settings)` picks the repo a
  command acts on (precedence: `--repo` > `METATRON_REPO` > persisted default >
  cwd-identity-if-in-store > sole repo > cwd-identity-if-store-empty; raises only when
  multiple repos and none chosen). Commands build the stores from `db_path`, resolve a
  repo, then filter by it.
- `metatron/repo_identity.py`: `repo_id(path)` = normalized `origin` remote, else
  directory name. A repo's identity is constant across machines because it keys on the
  remote, not the checkout path.
- The MCP server is **already per-repo**: `build_server(store, repo, event_store)`.

**Key observation:** every command already acts on exactly *one* resolved repo. The
only genuinely cross-repo operation is enumeration (`list_repos()`), used by the UI
picker and by `_resolve_repo`'s "sole repo"/"here in store" branches. This is why the
split is mostly a routing/discovery change, not a caller rewrite.

## Environment note: the placeholder parent dir

`/Users/pavel/dev/getmetatron` is **not** a git repo. It is a placeholder directory
holding sibling projects (`metatron`, `www-metatron`, …), each with its own `.git`
remote. Consequences the design must respect:

- **Repo identity always comes from the project's own remote.** `repo_id` already does
  this; we must never derive identity from the parent. Running `metatron` from the
  parent dir (no remote) would fall back to the dir name `getmetatron` — a footgun, but
  pre-existing and out of scope to "fix" here beyond documenting it.
- **The data dir is shared, not per-checkout.** To let one Metatron install ingest the
  sibling projects and ship any one of them, the catalog must live in a **single shared
  location**, not a cwd-relative folder that fragments per run directory.

## Design

### 1. The per-repo file is the unit

Each repo gets one SQLite file containing all of its data — `priors`, `events`,
`ingest_runs` — plus one new table:

```sql
CREATE TABLE IF NOT EXISTS repo_meta (repo_id TEXT NOT NULL);  -- exactly one row
```

`repo_meta` makes a file **self-describing**: the canonical repo id travels *inside*
the file, independent of its filename. This means (a) an empty repo is still
discoverable, and (b) a handed-off file announces which repo it is no matter what the
recipient names it.

The existing `repo` column on the three tables stays. Within a per-repo file it is
redundant (always equals `repo_meta.repo_id`), but keeping it means **the three store
classes in `sqlite.py` need no schema or query changes** — they just operate on a file
that happens to hold one repo. Filtering by `repo` remains correct (and is what makes
single-file mode and the migration copy trivially safe).

### 2. `RepoCatalog` — the only thing that knows files exist

New module `metatron/storage/catalog.py`. It owns the data directory and is the sole
place aware of the file layout:

- **Location:** default `~/.metatron/` (a single shared catalog, per the environment
  note). Overridable via the *same* knobs as today — `METATRON_DB` env / `db_path` in
  `metatron.toml`. (`db_path` semantics widen from "a file" to "a directory, or a single
  file"; see single-file mode.)
- **Filenames:** a collision-safe slug of the repo id plus a short hash of the full id,
  e.g. `github.com/acme/app` → `app-7f3a2c.db`. The filename is only a stable handle;
  the truth is `repo_meta`, so two local dirs both named `app` never clash.
- `list_repos() -> list[str]`: scan `*.db`, read each file's `repo_meta`. Replaces
  `store.list_repos()`.
- `open(repo_id) -> RepoStores`: returns the three stores bound to that repo's file,
  creating the file (with `repo_meta` written) on first use. Lazily opened, cached.
- `path_for(repo_id) -> Path`.

#### Single-file mode (the recipient's path)

If the configured path (`--db` / `METATRON_DB` / `db_path`) points at an existing
**file** rather than a directory, the catalog treats that one file as the entire world:
`list_repos()` returns the single id from its `repo_meta`, and `open()` returns its
stores. So `metatron --db received.db ui` "just works" — `_resolve_repo` sees exactly
one repo and selects it with no flags.

### 3. Wiring: callers barely change

- Add `open_repo(settings, repo_id) -> RepoStores` (a thin helper over the catalog)
  and replace the scattered `SQLitePriorStore(settings.db_path)` construction in
  `cli.py` and the MCP `serve` path.
- `_resolve_repo(...)` swaps `store.list_repos()` → `catalog.list_repos()`. Its
  precedence logic is otherwise unchanged. (Signature shifts from taking a `store` to
  taking a `catalog`; this is an internal helper, easy to thread through.)
- The MCP server already takes `(store, repo, event_store)` — `serve` resolves the repo,
  opens its file via the catalog, and passes those stores in. Smallest change of all.
- The local UI repo picker reads `catalog.list_repos()`; selecting a repo opens its file.
- "Get by id" methods (`get(prior_id)`, `set_status`, …) stay simple: the store is
  already scoped to the resolved repo's file, so there is **no cross-file id search**.

### 4. Auto-split migration (one-time, on upgrade)

On first catalog use, if a legacy single `metatron.db` exists (in the cwd / at the old
`db_path`) and the target `.metatron/` is not yet populated:

1. For each repo in the old DB, create its per-repo file and copy that repo's
   `priors` / `events` / `ingest_runs` across **via the stores** (read filtered by repo,
   write into the new file) — not raw SQL, so it stays schema-safe — and write
   `repo_meta`.
2. Archive the old file → `metatron.db.migrated-2026-06-06`. The archive's existence is
   the idempotency marker: migration never re-runs once the archive is present.

Pure data copy; no transformation. Safe to re-attempt if interrupted (re-creates files
from the still-present legacy DB until the archive rename succeeds).

### 5. `metatron export` (hand-off ergonomics)

`metatron export [--repo <id>] [--out PATH]`: copy the repo's per-repo file to `PATH`
(default `./<repo-name>.db`) and `VACUUM` it so the artifact is compact. `--repo`
resolves from context (see _resolve_repo) when omitted. Because a per-repo
file is *already* standalone, export is essentially a safe file copy with a vacuum — but
it gives a discoverable, documented command for the hand-off and a place to add options
later (e.g. `--without-events`).

Recipient flow: `metatron --db received.db ui` (or `serve`, `candidates`, …).

## CLI / UX summary

- `metatron <cmd>` — unchanged surface; data now lives in `~/.metatron/<slug>.db`.
- `metatron export [--repo <id>] [--out PATH]` — produce a shippable single-repo file. (New.)
- `metatron --db <file-or-dir> <cmd>` — point at a specific file (single-file mode, the
  recipient) or an alternate catalog dir. (Widened semantics of the existing knob.)
- First run after upgrade prints a one-line note that it migrated `metatron.db` into
  `~/.metatron/` and archived the original.

## Testing

- **Catalog:** slug determinism + collision-safety; `path_for`; `list_repos` scans and
  reads `repo_meta`; file created with `repo_meta` on first `open`; single-file-mode
  detection (file vs dir) and its `list_repos`/`open`.
- **Per-repo file:** the three stores operate unchanged against a per-repo file;
  `repo_meta` round-trips.
- **`_resolve_repo` over the catalog:** sole-repo, empty (cwd fallback), ambiguous
  (raises with guidance), cwd-identity-in-catalog — port the existing tests to the
  catalog.
- **Migration:** legacy DB with two repos → two per-repo files with correctly
  partitioned `priors`/`events`/`ingest_runs`; archive created; idempotent (second run
  is a no-op); interrupted-then-rerun still converges.
- **End-to-end:** ingest two repos → two files exist; `serve` repo A sees only A's
  priors; `list_repos` shows both; copy A's file to a temp path, open in single-file
  mode, `serve` answers tool calls.
- **Export:** `export --repo <id>` yields a file that opens cleanly in single-file mode and
  serves the same priors; output is vacuumed.

## Build order (small PRs, each with tests)

1. **`RepoCatalog` + `repo_meta` + single-file detection** — additive; nothing cut over
   yet. Stores gain the `repo_meta` table on init.
2. **Auto-split migration** of a legacy `metatron.db` into `~/.metatron/`.
3. **Cut callers over** to `open_repo`/catalog: `cli.py`, MCP `serve`, UI;
   `_resolve_repo` via catalog.
4. **`metatron export`** command.

## Risks / open questions

- **Default location change** (cwd-relative `metatron.db` → `~/.metatron/`). Justified
  by the shared-catalog requirement from the environment note, and softened by
  auto-migration + the overridable knob. Flagging explicitly because it changes where
  data lives for existing users.
- **Running from the non-git parent dir** still falls back to the `getmetatron` dir name
  as a repo id. Pre-existing behavior; documented, not fixed here.
- **Slug ↔ id drift:** filenames are slugs but identity is `repo_meta`, so a renamed
  file is fine; a *manually* duplicated file with the same `repo_meta` would make
  `list_repos` see one id twice — `list_repos` should de-dupe by id and warn.
