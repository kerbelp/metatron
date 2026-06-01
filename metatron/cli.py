"""Command-line entrypoint: ingest, serve, and curate priors.

Curation is human-in-the-loop by design — candidates only become canonical when
someone runs ``candidates approve``. Side-effecting dependencies (store, provider)
are injectable so the dispatch is testable; in normal use they are built from
:mod:`metatron.config`.
"""

from __future__ import annotations

import argparse
import sys
from typing import TextIO

from dotenv import find_dotenv, load_dotenv

from metatron.config import load_settings
from metatron.extraction.provider import AnthropicProvider, LLMProvider
from metatron.models import Status
from metatron.pipeline import ingest
from metatron.storage.base import PriorStore
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLitePriorStore,
)


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
    if store is None:
        store = SQLitePriorStore(settings.db_path)

    if args.command == "ingest":
        if provider is None:
            provider = AnthropicProvider(
                model=settings.model, api_key=settings.anthropic_api_key
            )
        return _cmd_ingest(
            args, store, provider,
            run_store or SQLiteIngestRunStore(settings.db_path), out,
        )
    if args.command == "serve":
        return _cmd_serve(
            store, args.repo, event_store or SQLiteEventStore(settings.db_path)
        )
    if args.command == "ui":
        return _cmd_ui(
            store,
            event_store or SQLiteEventStore(settings.db_path),
            SQLiteIngestRunStore(settings.db_path),
            args.port,
        )
    if args.command == "candidates":
        return _cmd_candidates(args, store, out)

    _build_parser().print_help(out)
    return 1


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


def _cmd_serve(store, repo, event_store) -> int:
    from metatron.mcp_server.server import build_server

    build_server(store, repo, event_store).run()
    return 0


def _cmd_ui(store, event_store, run_store, port) -> int:
    from metatron.webui.server import serve

    serve(store, event_store, start_port=port, run_store=run_store)
    return 0


def _cmd_candidates(args, store, out) -> int:
    if args.candidates_command == "list":
        return _candidates_list(store, args.repo, args.scope, out)
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
        "--repo", required=True, help="repo id to serve (the normalized origin remote)"
    )

    ui_p = sub.add_parser("ui", help="launch the local curation web UI")
    ui_p.add_argument(
        "--port", type=int, default=1337, help="starting port (bumps if taken)"
    )

    cand = sub.add_parser("candidates", help="review and curate candidate priors")
    cand_sub = cand.add_subparsers(dest="candidates_command")
    list_p = cand_sub.add_parser("list", help="list candidate priors")
    list_p.add_argument("--scope", default=None)
    list_p.add_argument("--repo", default=None, help="filter to one repo")
    approve_p = cand_sub.add_parser("approve", help="promote a candidate to canonical")
    approve_p.add_argument("id")
    reject_p = cand_sub.add_parser("reject", help="reject a candidate")
    reject_p.add_argument("id")

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
