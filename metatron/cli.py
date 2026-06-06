"""Command-line entrypoint: ingest, serve, and curate priors.

Curation is human-in-the-loop by design — candidates only become canonical when
someone runs ``candidates approve``. Side-effecting dependencies (store, provider)
are injectable so the dispatch is testable; in normal use they are built from
:mod:`metatron.config`.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import TextIO

from dotenv import find_dotenv, load_dotenv

from metatron import identity
from metatron.config import load_settings
from metatron.extraction.provider import AnthropicProvider, LLMProvider
from metatron.repo_identity import repo_id

# Feedback refinement defaults to Opus (overridable with --model); the global
# default model (Sonnet) is tuned for bulk extraction, not this higher-stakes step.
REFINE_MODEL = "claude-opus-4-8"
from metatron.models import Status
from metatron.pipeline import ingest
from metatron.storage.base import PriorStore
from metatron.storage.catalog import (
    Catalog,
    CatalogEventStore,
    CatalogIngestRunStore,
    CatalogPriorStore,
)
from metatron.storage.migrate import migrate_legacy_db
from metatron.storage.sqlite import SQLiteEventStore, SQLiteIngestRunStore


class RepoResolutionError(Exception):
    """Raised when the repo to act on is ambiguous and the user must disambiguate."""


def _resolve_repo(explicit: str | None, store: PriorStore, settings) -> str:
    """The repo id a command should act on, git-style.

    Precedence, highest first:

    1. explicit ``--repo``
    2. ``METATRON_REPO`` env (a per-shell session context)
    3. a persisted default (set via ``metatron repo set``)
    4. the current directory's identity (origin remote, else dir name) *if it is a
       repo already in the store* — so running inside a tracked repo just works
    5. the only repo in the store, if there is exactly one
    6. the current directory's identity, when the store is empty (nothing to act on)

    If none of these resolve and the store holds more than one repo, we refuse to
    guess and raise :class:`RepoResolutionError` with the choices and how to pick.
    """
    if explicit:
        return explicit
    env = os.environ.get("METATRON_REPO")
    if env:
        return env
    if settings.default_repo:
        return settings.default_repo

    repos = store.list_repos()
    here = repo_id(".")
    if here in repos:
        return here
    if len(repos) == 1:
        return repos[0]
    if not repos:
        return here

    listed = "\n".join(f"  - {r}" for r in repos)
    raise RepoResolutionError(
        "Multiple repos in the store — can't tell which one you mean:\n"
        f"{listed}\n\n"
        "Choose one with `--repo <id>`, export METATRON_REPO=<id> for this shell, "
        "or set a default with `metatron repo set <id>`."
    )


def _resolve_and_announce(explicit, store, settings, out) -> str:
    """Resolve the repo and echo it, so the acted-on repo is always visible."""
    repo = _resolve_repo(explicit, store, settings)
    print(f"Repo: {repo}", file=out)
    return repo


def main(
    argv: list[str] | None = None,
    *,
    store: PriorStore | None = None,
    provider: LLMProvider | None = None,
    event_store: SQLiteEventStore | None = None,
    run_store: SQLiteIngestRunStore | None = None,
    out: TextIO | None = None,
) -> int:
    out = out if out is not None else sys.stdout

    # Load a .env from the working directory (does not override exported vars),
    # so ANTHROPIC_API_KEY and other settings can live there. Only ingest needs
    # the key, but loading early keeps every command's environment consistent.
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)

    args = _build_parser().parse_args(argv)

    settings = load_settings()
    if args.db:
        settings = settings.model_copy(update={"db_path": args.db})

    # The catalog is the source of truth: one self-contained DB file per repo under
    # settings.db_path (a directory), or a single handed-off file in single-file mode.
    try:
        catalog = Catalog(settings.db_path)
    except FileNotFoundError as exc:
        print(exc, file=out)
        return 2
    # One-time split of a legacy cwd metatron.db into the catalog. Guarded so a
    # migration hiccup never takes down unrelated commands; the copy is idempotent,
    # so re-running converges. The legacy file is left untouched until it fully lands.
    try:
        migrate_legacy_db("metatron.db", catalog)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't brick the CLI
        print(f"Warning: could not migrate legacy metatron.db: {exc}", file=out)
        print("Your data is preserved in metatron.db; re-run to retry.", file=out)

    if store is None:
        store = CatalogPriorStore(catalog)
    event_store = event_store or CatalogEventStore(catalog)
    run_store = run_store or CatalogIngestRunStore(catalog)

    try:
        if args.command == "ingest":
            if provider is None:
                provider = AnthropicProvider(
                    model=settings.model, api_key=settings.anthropic_api_key
                )
            return _cmd_ingest(args, store, provider, run_store, out)
        if args.command == "serve":
            # MCP speaks over stdout, so resolve silently — no "Repo:" header here.
            return _cmd_serve(
                store, _resolve_repo(args.repo, store, settings), event_store,
            )
        if args.command == "repo":
            return _cmd_repo(args, store, settings, out)
        if args.command == "ui":
            return _cmd_ui(store, event_store, run_store, args.port, settings)
        if args.command == "triage":
            if provider is None:
                provider = AnthropicProvider(
                    model=settings.model, api_key=settings.anthropic_api_key
                )
            return _cmd_triage(args, store, provider, settings, out)
        if args.command == "refine-feedback":
            if provider is None:
                # Reshaping feedback is higher-stakes than extraction — default to Opus.
                provider = AnthropicProvider(
                    model=args.model or REFINE_MODEL, api_key=settings.anthropic_api_key
                )
            return _cmd_refine_feedback(
                args, store, event_store, provider, settings, out,
            )
        if args.command == "whoami":
            return _cmd_whoami(args, out)
        if args.command == "export":
            return _cmd_export(
                catalog, _resolve_repo(args.repo, store, settings), args.out, out
            )
        if args.command == "candidates":
            return _cmd_candidates(args, store, settings, out)
    except RepoResolutionError as exc:
        print(exc, file=out)
        return 2

    _build_parser().print_help(out)
    return 1


def _ingest_progress(out):
    """A progress reporter for ingest: a header, then a line as each scope is extracted.

    Extraction is one LLM call per scope; without this a large repo looks hung for
    minutes. The first report (scopes_done=0) carries the parsed totals for a header.
    """
    def report(p: dict) -> None:
        total = p["scopes_total"]
        if p["scopes_done"] == 0:
            print(
                f"Ingesting {p['repo']}: parsed {p['files_parsed']} files, "
                f"{p['commits_read']} commits across {total} scope(s) — extracting…",
                file=out, flush=True,
            )
        else:
            print(
                f"  [{p['scopes_done']}/{total}] {p['priors_created']} candidate(s) so far …",
                file=out, flush=True,
            )

    return report


def _cmd_ingest(args, store, provider, run_store, out) -> int:
    result = ingest(
        args.repo_path,
        store,
        provider,
        repo=args.repo,
        max_commits=args.max_commits,
        since=args.since,
        path_prefix=args.path,
        run_store=run_store,
        on_progress=_ingest_progress(out),
    )
    print(
        f"Ingested repo '{result.repo}' from {args.repo_path}: "
        f"parsed {result.files_parsed} files, read {result.commits_read} commits "
        f"across {result.scopes} scopes, created {result.priors_created} candidate priors.",
        file=out,
    )
    print(f"Review them with: metatron candidates list --repo {result.repo}", file=out)
    print(f"Serve them with:  metatron serve --repo {result.repo}", file=out)
    return 0


def _cmd_whoami(args, out) -> int:
    """Show or set the local identity that ``serve`` stamps onto events."""
    if args.set_email is not None or args.set_name is not None:
        ident = identity.set_identity(email=args.set_email, display_name=args.set_name)
    else:
        ident = identity.ensure_identity()  # seed from git on first use
    if not (ident.actor_id or ident.email):
        print("No identity set (events will be recorded anonymously).", file=out)
        print("Set one with: metatron whoami --set-email you@corp.com --set-name 'Your Name'", file=out)
        return 0
    print(f"{ident.display_name or '(no name)'} <{ident.email or 'no-email'}>", file=out)
    print(f"actor_id: {ident.actor_id}", file=out)
    print(f"config:   {identity.config_path()}", file=out)
    return 0


def _cmd_export(catalog, repo: str, out: str | None, out_stream) -> int:
    """Copy a repo's self-contained DB out for hand-off, then VACUUM it.

    The per-repo file is already standalone; export is a consistent snapshot (sqlite
    backup) plus a vacuum so the artifact is compact. The recipient opens it directly
    with ``metatron --db <file> ...`` (single-file mode) — no MCP, no re-ingest.
    """
    if repo not in catalog.list_repos():
        print(f"No data for repo '{repo}'.", file=out_stream)
        return 2
    src = catalog.path_for(repo)
    dst = Path(out) if out else Path(f"{repo.rstrip('/').split('/')[-1]}.db")
    s = sqlite3.connect(src)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)  # consistent copy of the whole per-repo file
        d.execute("VACUUM")
    finally:
        s.close()
        d.close()
    print(f"Exported '{repo}' → {dst}", file=out_stream)
    print(f"Recipient: metatron --db {dst} ui", file=out_stream)
    return 0


def _cmd_serve(store, repo, event_store) -> int:
    from metatron.mcp_server.server import build_server

    build_server(store, repo, event_store).run()
    return 0


def _cmd_ui(store, event_store, run_store, port, settings) -> int:
    from metatron.webui.server import serve

    # The UI's manual "Refine" button needs an LLM provider. Build it lazily (only
    # when a button is clicked) and only if a key is configured — otherwise the button
    # reports refinement is unavailable rather than the server failing to start. Opus,
    # like the `refine-feedback` CLI, since reshaping feedback is the higher-stakes step.
    refiner_factory = None
    ingest_provider_factory = None
    if settings.anthropic_api_key:
        def refiner_factory():
            from metatron.extraction.feedback_refiner import FeedbackRefiner

            provider = AnthropicProvider(
                model=REFINE_MODEL, api_key=settings.anthropic_api_key
            )
            return FeedbackRefiner(provider, model=REFINE_MODEL)

        def ingest_provider_factory():
            # Ingest uses the default (bulk-tuned) model, like the CLI.
            return AnthropicProvider(
                model=settings.model, api_key=settings.anthropic_api_key
            )

    serve(
        store, event_store, start_port=port, run_store=run_store,
        refiner_factory=refiner_factory,
        ingest_provider_factory=ingest_provider_factory,
    )
    return 0


def _cmd_triage(args, store, provider, settings, out) -> int:
    from collections import Counter

    from metatron.extraction.triage import PriorJudge
    from metatron.models import TriageVerdict
    from metatron.pricing import estimate_cost

    repo = _resolve_and_announce(args.repo, store, settings, out)
    candidates = store.list(
        repo=repo,
        status=Status.CANDIDATE,
        triage=TriageVerdict.NONE,
        limit=args.limit,
    )
    if not candidates:
        print("No untriaged candidate priors.", file=out)
        return 0

    results = PriorJudge(provider).evaluate(candidates, on_progress=_triage_progress(out))
    for prior_id, (verdict, reason) in results.items():
        try:
            store.set_triage(prior_id, verdict, reason)
        except KeyError:
            continue  # defensive: ignore any verdict that doesn't map to a prior

    counts = Counter(verdict.value for verdict, _ in results.values())
    print(
        f"Triaged {len(results)} candidates: "
        + ", ".join(f"{v}={counts.get(v, 0)}" for v in ("approve", "borderline", "reject")),
        file=out,
    )
    cost = estimate_cost(
        getattr(provider, "model", ""),
        getattr(provider, "input_tokens", 0),
        getattr(provider, "output_tokens", 0),
    )
    if cost is not None:
        print(f"  judge cost: ~${cost:.2f}", file=out)
    print("Review by recommendation in the UI's Candidates filter.", file=out)
    return 0


def _triage_progress(out):
    """A progress reporter for triage: a header, then a line per judged batch.

    The judge runs one LLM call per batch (15 candidates), so without this a long
    queue looks hung. A line prints as each batch goes in flight.
    """
    def report(p: dict) -> None:
        total = p["candidates_total"]
        batches = p["batches_total"]
        if p["phase"] == "start":
            if total:
                print(
                    f"Judging {total} candidate(s) in {batches} batch(es) — "
                    "one call each, this can take a moment…",
                    file=out, flush=True,
                )
        elif p["phase"] == "judging":
            print(
                f"  [batch {p['batches_done'] + 1}/{batches}] "
                f"{p['candidates_done']}/{total} judged so far …",
                file=out, flush=True,
            )

    return report


def _refine_progress(out):
    """A progress reporter for refine-feedback: one live line per event.

    Each event is a slow Opus round-trip, so without this the CLI looks hung. We
    print the count up front, then a line as each event goes in flight (so the
    next line appearing means the previous one finished).
    """
    def report(p: dict) -> None:
        total = p["events_total"]
        if p["phase"] == "start":
            if total:
                print(
                    f"Refining {total} unhandled feedback report(s) — "
                    "one Opus call each, this can take a moment…",
                    file=out, flush=True,
                )
        elif p["phase"] == "refining":
            area = p.get("area") or "global"
            print(f"  [{p['events_done'] + 1}/{total}] {area} …", file=out, flush=True)

    return report


def _cmd_refine_feedback(args, store, event_store, provider, settings, out) -> int:
    from metatron.extraction.feedback_refiner import FeedbackRefiner
    from metatron.pipeline import refine_feedback
    from metatron.pricing import estimate_cost

    repo = _resolve_and_announce(args.repo, store, settings, out)
    refiner = FeedbackRefiner(provider, model=getattr(provider, "model", ""))
    result = refine_feedback(
        store, event_store, refiner, repo=repo, limit=args.limit,
        on_progress=_refine_progress(out),
    )
    if result.events_processed == 0:
        print("No unhandled feedback to refine.", file=out)
        return 0
    print(
        f"Refined {result.events_processed} feedback report(s) into "
        f"{result.priors_created} candidate prior(s) for curation.",
        file=out,
    )
    cost = estimate_cost(
        getattr(provider, "model", ""),
        getattr(provider, "input_tokens", 0),
        getattr(provider, "output_tokens", 0),
    )
    if cost is not None:
        print(f"  refiner cost: ~${cost:.2f}", file=out)
    print("Review them in the UI Candidates tab (origin: feedback).", file=out)
    return 0


def _cmd_repo(args, store, settings, out) -> int:
    if args.repo_command == "list":
        return _repo_list(store, settings, out)
    if args.repo_command == "set":
        return _repo_set(args.id, out)
    if args.repo_command == "unset":
        return _repo_unset(out)
    return 1


def _repo_list(store, settings, out) -> int:
    repos = store.list_repos()
    if not repos:
        print("No repos yet. Run `metatron ingest <path>` to bootstrap one.", file=out)
        return 0
    for r in repos:
        canonical = store.count(repo=r, status=Status.CANONICAL)
        candidates = store.count(repo=r, status=Status.CANDIDATE)
        marker = "  (default)" if r == settings.default_repo else ""
        print(f"{r}  (canonical={canonical}, candidates={candidates}){marker}", file=out)
    return 0


def _repo_set(repo: str, out) -> int:
    from metatron.config import update_settings

    update_settings({"default_repo": repo})
    print(f"Default repo set to {repo} (saved to metatron.toml).", file=out)
    print("Commands now act on it unless --repo or METATRON_REPO overrides.", file=out)
    return 0


def _repo_unset(out) -> int:
    from metatron.config import update_settings

    update_settings({"default_repo": None})
    print("Default repo cleared.", file=out)
    return 0


def _cmd_candidates(args, store, settings, out) -> int:
    if args.candidates_command == "list":
        repo = _resolve_and_announce(args.repo, store, settings, out)
        return _candidates_list(store, repo, args.scope, out)
    if args.candidates_command == "approve":
        return _set_status(store, args.id, Status.CANONICAL, "approved", out)
    if args.candidates_command == "reject":
        return _set_status(store, args.id, Status.REJECTED, "rejected", out)
    return 1


def _candidates_list(store, repo, scope, out) -> int:
    candidates = store.list(repo=repo, status=Status.CANDIDATE, scope=scope)
    if not candidates:
        print("No candidate priors.", file=out)
        return 0
    for p in candidates:
        print(f"{p.id}  [{p.confidence.value}]  ({p.scope or 'global'})", file=out)
        print(f"    {p.pattern}", file=out)
    return 0


def _set_status(store, prior_id, status, verb, out) -> int:
    try:
        store.set_status(prior_id, status)
    except KeyError:
        print(f"No prior with id {prior_id!r} (not found).", file=out)
        return 1
    print(f"Prior {prior_id} {verb}.", file=out)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metatron")
    parser.add_argument(
        "--db",
        default=None,
        help="catalog directory, or a single repo's .db file (single-file mode); "
        "overrides METATRON_DB / metatron.toml for this run",
    )
    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="bootstrap candidate priors from a repo")
    ingest_p.add_argument("repo_path", help="path to a local git repo")
    ingest_p.add_argument("--max-commits", type=int, default=500)
    ingest_p.add_argument("--since", default=None, help="e.g. 2024-01-01")
    ingest_p.add_argument(
        "--path",
        default=None,
        help="limit ingest to a subtree, e.g. src/components",
    )
    ingest_p.add_argument(
        "--repo",
        default=None,
        help="override the repo id (defaults to the normalized origin remote)",
    )

    serve_p = sub.add_parser("serve", help="serve one repo's priors to agents over MCP")
    serve_p.add_argument(
        "--repo",
        default=None,
        help="repo id to serve (defaults to METATRON_REPO, else the current dir's id)",
    )

    repo_p = sub.add_parser("repo", help="inspect and choose the repo commands act on")
    repo_sub = repo_p.add_subparsers(dest="repo_command")
    repo_sub.add_parser("list", help="list repos with their prior counts (the ids serve uses)")
    repo_set_p = repo_sub.add_parser(
        "set", help="persist a default repo (saved to metatron.toml)"
    )
    repo_set_p.add_argument("id", help="the repo id to use by default")
    repo_sub.add_parser("unset", help="clear the persisted default repo")

    ui_p = sub.add_parser("ui", help="launch the local curation web UI")
    ui_p.add_argument(
        "--port", type=int, default=1337, help="starting port (bumps if taken)"
    )

    whoami_p = sub.add_parser(
        "whoami", help="show or set the local identity stamped onto served events"
    )
    whoami_p.add_argument("--set-email", default=None, help="set your email")
    whoami_p.add_argument("--set-name", default=None, help="set your display name")

    triage_p = sub.add_parser(
        "triage", help="run the advisory judge over candidate priors (does not auto-curate)"
    )
    triage_p.add_argument(
        "--repo", default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    triage_p.add_argument("--limit", type=int, default=None, help="max candidates to judge")

    refine_p = sub.add_parser(
        "refine-feedback",
        help="reshape captured agent feedback into structured candidate priors (Opus)",
    )
    refine_p.add_argument(
        "--repo", default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    refine_p.add_argument("--limit", type=int, default=None, help="max feedback reports to refine")
    refine_p.add_argument(
        "--model", default=None, help=f"override the refiner model (default {REFINE_MODEL})"
    )

    cand = sub.add_parser("candidates", help="review and curate candidate priors")
    cand_sub = cand.add_subparsers(dest="candidates_command")
    list_p = cand_sub.add_parser("list", help="list candidate priors")
    list_p.add_argument("--scope", default=None)
    list_p.add_argument(
        "--repo",
        default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    approve_p = cand_sub.add_parser("approve", help="promote a candidate to canonical")
    approve_p.add_argument("id")
    reject_p = cand_sub.add_parser("reject", help="reject a candidate")
    reject_p.add_argument("id")

    export_p = sub.add_parser(
        "export", help="copy a repo's self-contained DB out for hand-off"
    )
    export_p.add_argument(
        "--repo", default=None,
        help="repo id to export (defaults to METATRON_REPO, else the sole/current repo)",
    )
    export_p.add_argument(
        "--out", default=None, help="destination path (default ./<repo-name>.db)"
    )

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
