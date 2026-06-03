"""Command-line entrypoint: ingest, serve, and curate priors.

Curation is human-in-the-loop by design — candidates only become canonical when
someone runs ``candidates approve``. Side-effecting dependencies (store, provider)
are injectable so the dispatch is testable; in normal use they are built from
:mod:`metatron.config`.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import TextIO

from dotenv import find_dotenv, load_dotenv

from metatron.config import load_settings
from metatron.extraction.provider import AnthropicProvider, LLMProvider
from metatron.repo_identity import repo_id

# Feedback refinement defaults to Opus (overridable with --model); the global
# default model (Sonnet) is tuned for bulk extraction, not this higher-stakes step.
REFINE_MODEL = "claude-opus-4-8"
from metatron.models import Status
from metatron.pipeline import ingest
from metatron.storage.base import PriorStore
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLitePriorStore,
)


def _resolve_repo(explicit: str | None) -> str:
    """The repo id a command should act on, git-style.

    Precedence: explicit ``--repo`` > ``METATRON_REPO`` env (a session-wide
    context) > the current directory's identity (its origin remote, falling back
    to the directory name). So you rarely need to pass ``--repo`` — run commands
    from inside the repo, or export ``METATRON_REPO`` once.
    """
    if explicit:
        return explicit
    env = os.environ.get("METATRON_REPO")
    if env:
        return env
    return repo_id(".")


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
            store, _resolve_repo(args.repo), event_store or SQLiteEventStore(settings.db_path)
        )
    if args.command == "repo":
        return _cmd_repo(args, store, out)
    if args.command == "ui":
        return _cmd_ui(
            store,
            event_store or SQLiteEventStore(settings.db_path),
            SQLiteIngestRunStore(settings.db_path),
            args.port,
            settings,
        )
    if args.command == "triage":
        if provider is None:
            provider = AnthropicProvider(
                model=settings.model, api_key=settings.anthropic_api_key
            )
        return _cmd_triage(args, store, provider, out)
    if args.command == "refine-feedback":
        if provider is None:
            # Reshaping feedback is higher-stakes than extraction — default to Opus.
            provider = AnthropicProvider(
                model=args.model or REFINE_MODEL, api_key=settings.anthropic_api_key
            )
        return _cmd_refine_feedback(
            args, store, event_store or SQLiteEventStore(settings.db_path), provider, out
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


def _cmd_ui(store, event_store, run_store, port, settings) -> int:
    from metatron.webui.server import serve

    # The UI's manual "Refine" button needs an LLM provider. Build it lazily (only
    # when a button is clicked) and only if a key is configured — otherwise the button
    # reports refinement is unavailable rather than the server failing to start. Opus,
    # like the `refine-feedback` CLI, since reshaping feedback is the higher-stakes step.
    refiner_factory = None
    if settings.anthropic_api_key:
        def refiner_factory():
            from metatron.extraction.feedback_refiner import FeedbackRefiner

            provider = AnthropicProvider(
                model=REFINE_MODEL, api_key=settings.anthropic_api_key
            )
            return FeedbackRefiner(provider, model=REFINE_MODEL)

    serve(
        store, event_store, start_port=port, run_store=run_store,
        refiner_factory=refiner_factory,
    )
    return 0


def _cmd_triage(args, store, provider, out) -> int:
    from collections import Counter

    from metatron.extraction.triage import PriorJudge
    from metatron.models import TriageVerdict
    from metatron.pricing import estimate_cost

    candidates = store.list(
        repo=_resolve_repo(args.repo),
        status=Status.CANDIDATE,
        triage=TriageVerdict.NONE,
        limit=args.limit,
    )
    if not candidates:
        print("No untriaged candidate priors.", file=out)
        return 0

    results = PriorJudge(provider).evaluate(candidates)
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


def _cmd_refine_feedback(args, store, event_store, provider, out) -> int:
    from metatron.extraction.feedback_refiner import FeedbackRefiner
    from metatron.pipeline import refine_feedback
    from metatron.pricing import estimate_cost

    refiner = FeedbackRefiner(provider, model=getattr(provider, "model", ""))
    result = refine_feedback(
        store, event_store, refiner, repo=_resolve_repo(args.repo), limit=args.limit
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


def _cmd_repo(args, store, out) -> int:
    if args.repo_command == "list":
        return _repo_list(store, out)
    return 1


def _repo_list(store, out) -> int:
    repos = store.list_repos()
    if not repos:
        print("No repos yet. Run `metatron ingest <path>` to bootstrap one.", file=out)
        return 0
    for r in repos:
        canonical = store.count(repo=r, status=Status.CANONICAL)
        candidates = store.count(repo=r, status=Status.CANDIDATE)
        print(f"{r}  (canonical={canonical}, candidates={candidates})", file=out)
    return 0


def _cmd_candidates(args, store, out) -> int:
    if args.candidates_command == "list":
        return _candidates_list(store, _resolve_repo(args.repo), args.scope, out)
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
        "--repo",
        default=None,
        help="repo id to serve (defaults to METATRON_REPO, else the current dir's id)",
    )

    repo_p = sub.add_parser("repo", help="inspect the repos in the store")
    repo_sub = repo_p.add_subparsers(dest="repo_command")
    repo_sub.add_parser("list", help="list repos with their prior counts (the ids serve uses)")

    ui_p = sub.add_parser("ui", help="launch the local curation web UI")
    ui_p.add_argument(
        "--port", type=int, default=1337, help="starting port (bumps if taken)"
    )

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

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
