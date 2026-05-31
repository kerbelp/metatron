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
from metatron.storage.sqlite import SQLitePriorStore


def main(
    argv: list[str] | None = None,
    *,
    store: PriorStore | None = None,
    provider: LLMProvider | None = None,
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
        return _cmd_ingest(args, store, provider, out)
    if args.command == "serve":
        return _cmd_serve(store)
    if args.command == "candidates":
        return _cmd_candidates(args, store, out)

    _build_parser().print_help(out)
    return 1


def _cmd_ingest(args, store, provider, out) -> int:
    result = ingest(
        args.repo_path,
        store,
        provider,
        max_commits=args.max_commits,
        since=args.since,
    )
    print(
        f"Ingested {args.repo_path}: parsed {result.files_parsed} files, "
        f"read {result.commits_read} commits across {result.scopes} scopes, "
        f"created {result.priors_created} candidate priors.",
        file=out,
    )
    print("Review them with: metatron candidates list", file=out)
    return 0


def _cmd_serve(store) -> int:
    from metatron.mcp_server.server import build_server

    build_server(store).run()
    return 0


def _cmd_candidates(args, store, out) -> int:
    if args.candidates_command == "list":
        return _candidates_list(store, args.scope, out)
    if args.candidates_command == "approve":
        return _set_status(store, args.id, Status.CANONICAL, "approved", out)
    if args.candidates_command == "reject":
        return _set_status(store, args.id, Status.REJECTED, "rejected", out)
    return 1


def _candidates_list(store, scope, out) -> int:
    candidates = store.list(status=Status.CANDIDATE, scope=scope)
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

    sub.add_parser("serve", help="serve priors to agents over MCP (stdio)")

    cand = sub.add_parser("candidates", help="review and curate candidate priors")
    cand_sub = cand.add_subparsers(dest="candidates_command")
    list_p = cand_sub.add_parser("list", help="list candidate priors")
    list_p.add_argument("--scope", default=None)
    approve_p = cand_sub.add_parser("approve", help="promote a candidate to canonical")
    approve_p.add_argument("id")
    reject_p = cand_sub.add_parser("reject", help="reject a candidate")
    reject_p.add_argument("id")

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
