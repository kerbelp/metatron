"""Command-line entrypoint: ingest, serve, and curate decisions.

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
from metatron.config import load_settings, resolve_context_dir
from metatron.version import package_version, version_string, check_for_update, format_update_notice
from metatron.extraction.provider import AnthropicProvider, LLMProvider
from metatron.repo_identity import repo_id

from metatron.models import Status
from metatron.pipeline import ingest
from metatron.storage.base import DecisionStore
from metatron.storage.catalog import (
    Catalog,
    CatalogEventStore,
    CatalogIngestRunStore,
    CatalogDecisionStore,
)
from metatron.storage.migrate import migrate_legacy_db
from metatron.storage.sqlite import SQLiteEventStore, SQLiteIngestRunStore

# Feedback refinement defaults to Opus (overridable with --model); the global
# default model (Sonnet) is tuned for bulk extraction, not this higher-stakes step.
REFINE_MODEL = "claude-opus-4-8"


class RepoResolutionError(Exception):
    """Raised when the repo to act on is ambiguous and the user must disambiguate."""


def _resolve_repo(explicit: str | None, store: DecisionStore, settings) -> str:
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


_TAGLINE = "Capture your team's engineering decisions and serve them to AI coding agents over MCP."


def _subcommands(parser):
    """Yield (name, help) for each registered subcommand, in definition order."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                yield choice.dest, (choice.help or "")
            return


def _render_home(parser, out) -> int:
    """The landing screen shown for a bare ``metatron`` invocation."""
    is_tty = bool(getattr(out, "isatty", lambda: False)())

    def style(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if is_tty else text

    print(f"{style('metatron', '1')} · {_TAGLINE}", file=out)
    print("\nUsage:\n  metatron [--db PATH] <command> [flags]\n", file=out)
    print("Available commands:", file=out)
    for name, help_text in _subcommands(parser):
        print(f"  {name:<17} {help_text}", file=out)
    print('\nRun "metatron <command> --help" for more about a command.', file=out)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    store: DecisionStore | None = None,
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

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Bare `metatron` (no subcommand): show the branded home screen and stop —
    # before touching the catalog, so it has no side effects.
    if args.command is None:
        return _render_home(parser, out)

    if args.command == "version":
        print(f"metatron {package_version()} (rev {version_string()})", file=out)
        if getattr(args, "upgrade", False):
            return _cmd_version_upgrade(out)
        notice = format_update_notice(check_for_update())
        if notice:
            print(notice, file=out)
        return 0

    if args.command == "files":
        return _cmd_files(args, out)

    if args.command == "context":
        return _cmd_context(args, out)

    if args.command == "verification":
        return _cmd_verification(args, out)

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
        store = CatalogDecisionStore(catalog)
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
            if getattr(args, "files", False):
                return _cmd_ui_files(args, settings, out)
            return _cmd_ui(store, event_store, run_store, args.port, settings)
        if args.command == "triage":
            if provider is None:
                provider = AnthropicProvider(
                    model=settings.model, api_key=settings.anthropic_api_key
                )
            return _cmd_triage(args, store, provider, settings, out)
        if args.command == "enrich-keywords":
            if provider is None:
                provider = AnthropicProvider(
                    model=settings.model, api_key=settings.anthropic_api_key
                )
            return _cmd_enrich_keywords(args, store, provider, settings, out)
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
        if args.command == "import":
            return _cmd_import(catalog, args.path, out)
        if args.command == "candidates":
            return _cmd_candidates(args, store, settings, out)
        if args.command == "mirror":
            return _cmd_mirror(args, store, event_store, settings, out)
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
                f"  [{p['scopes_done']}/{total}] {p['decisions_created']} candidate(s) so far …",
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
        f"across {result.scopes} scopes, created {result.decisions_created} candidate decisions.",
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


def _cmd_import(catalog, path: str, out_stream) -> int:
    """Merge another employee's per-repo DB (file or catalog dir) into this catalog.

    Dedupes by id, so re-importing the same file is a no-op. Event attribution travels
    with the rows, so a curator sees who contributed what after the merge.
    """
    from metatron.storage.catalog import Catalog
    from metatron.storage.transfer import import_catalog

    src = Path(path)
    if not src.exists():
        print(f"No such file or directory: {src}", file=out_stream)
        return 2
    counts = import_catalog(Catalog(str(src)), catalog)
    if not counts:
        print(f"Nothing to import from {src} (no repos found).", file=out_stream)
        return 0
    for repo, c in counts.items():
        print(
            f"Imported '{repo}': {c['decisions']} decisions, {c['events']} events, "
            f"{c['runs']} ingest runs.",
            file=out_stream,
        )
    return 0


def _cmd_serve(store, repo, event_store) -> int:
    from metatron.mcp_server.server import build_server

    # Stamp served events with the local employee identity (seeded from git on first
    # use), so feedback/queries are attributable once DBs are merged.
    build_server(store, repo, event_store, identity=identity.ensure_identity()).run()
    return 0


def _cmd_ui_files(args, settings, out) -> int:
    """Files-first UI: mount a repo's OKF bundle behind a throwaway index.

    The store is in-memory and rebuilt from the files at startup — the git
    working tree remains the only durable state, matching the files-first
    contract everywhere else in the CLI.
    """
    from metatron.storage.sqlite import SQLiteDecisionStore, SQLiteEventStore
    from metatron.webui.files_mode import FilesMode
    from metatron.webui.server import serve

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"no such directory: {root}", file=out)
        return 1
    store = SQLiteDecisionStore(":memory:")
    fm = FilesMode(store, root, context_dir=settings.context_dir)
    if not fm.kb_dir().is_dir():
        print(f"no knowledge base at {fm.kb_dir()} — run `metatron context setup` first",
              file=out)
        return 1
    res = fm.refresh()
    for w in res.warnings:
        print(f"warning: {w}", file=out)
    print(f"Files mode: {fm.kb_dir()} ({len(store.list(repo=fm.repo))} decisions; "
          "edits become git working-tree changes — review and commit via git)", file=out)
    serve(store, SQLiteEventStore(":memory:"), start_port=args.port, files_mode=fm)
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

    # Warn about an available update before the server takes over the terminal.
    # On a cache hit this is one file read; on a miss it is a 1.5s-timeout, fail-silent check.
    notice = format_update_notice(check_for_update())
    if notice:
        print(notice, file=sys.stderr)

    serve(
        store, event_store, start_port=port, run_store=run_store,
        refiner_factory=refiner_factory,
        ingest_provider_factory=ingest_provider_factory,
    )
    return 0


def _cmd_triage(args, store, provider, settings, out) -> int:
    from collections import Counter

    from metatron.extraction.triage import DecisionJudge
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
        print("No untriaged candidate decisions.", file=out)
        return 0

    results = DecisionJudge(provider).evaluate(candidates, on_progress=_triage_progress(out))
    for decision_id, (verdict, reason) in results.items():
        try:
            store.set_triage(decision_id, verdict, reason)
        except KeyError:
            continue  # defensive: ignore any verdict that doesn't map to a decision

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


def _cmd_enrich_keywords(args, store, provider, settings, out) -> int:
    from metatron.extraction.enrich import KeywordEnricher
    from metatron.pricing import estimate_cost

    repo = _resolve_and_announce(args.repo, store, settings, out)
    # Canonical only by default: those are the decisions being served, so they are
    # where missing keywords cost retrieval. Candidates gain keywords at extraction
    # going forward and get enriched here once approved.
    decisions = [
        p for p in store.list(repo=repo, status=Status.CANONICAL, limit=args.limit)
        if not p.keywords
    ]
    if not decisions:
        print("No canonical decisions are missing keywords.", file=out)
        return 0

    results = KeywordEnricher(provider).enrich(
        decisions, on_progress=_enrich_progress(out)
    )
    for decision_id, keywords in results.items():
        try:
            store.set_keywords(decision_id, keywords)
        except KeyError:
            continue  # defensive: a decision deleted mid-run is not fatal

    print(f"Enriched {len(results)} of {len(decisions)} decision(s) with keywords.", file=out)
    cost = estimate_cost(
        getattr(provider, "model", ""),
        getattr(provider, "input_tokens", 0),
        getattr(provider, "output_tokens", 0),
    )
    if cost is not None:
        print(f"  enrich cost: ~${cost:.2f}", file=out)
    return 0


def _enrich_progress(out):
    """A progress reporter for enrich-keywords: a header, then a line per batch."""
    def report(p: dict) -> None:
        total = p["decisions_total"]
        batches = p["batches_total"]
        if p["phase"] == "start":
            if total:
                print(
                    f"Enriching {total} decision(s) in {batches} batch(es) — "
                    "one call each, this can take a moment…",
                    file=out, flush=True,
                )
        elif p["phase"] == "enriching":
            print(
                f"  [batch {p['batches_done'] + 1}/{batches}] "
                f"{p['decisions_done']}/{total} enriched so far …",
                file=out, flush=True,
            )

    return report


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
        f"{result.decisions_created} candidate decision(s) for curation.",
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
        print("No candidate decisions.", file=out)
        return 0
    for p in candidates:
        print(f"{p.id}  [{p.confidence.value}]  ({p.scope or 'global'})", file=out)
        print(f"    {p.pattern}", file=out)
    return 0


def _set_status(store, decision_id, status, verb, out) -> int:
    try:
        store.set_status(decision_id, status)
    except KeyError:
        print(f"No decision with id {decision_id!r} (not found).", file=out)
        return 1
    print(f"Decision {decision_id} {verb}.", file=out)
    return 0


def _cmd_mirror(args, store, event_store, settings, out) -> int:
    repo = _resolve_and_announce(args.repo, store, settings, out)
    root = Path(args.root)
    context_dir = getattr(args, "context_dir", None) or settings.context_dir
    if args.mirror_command == "sync":
        events = event_store.list_events(repo=repo)
        # Imported lazily on purpose: keeps the mirror modules (and their yaml
        # dependency) off the import path of unrelated, hot CLI commands.
        from metatron.mirror.export import export_bundle
        from metatron.mirror.okf import export_okf_bundle

        if getattr(args, "okf", False):
            export_okf_bundle(store, repo=repo, root=root, events=events,
                              context_dir=context_dir)
        else:
            export_bundle(store, repo=repo, root=root, events=events,
                          context_dir=context_dir)
        print("Mirror synced.", file=out)
        return 0
    if args.mirror_command == "import":
        # Lazy import (see sync above): mirror deps stay off the hot path for
        # unrelated commands.
        from metatron.mirror.sync_import import import_bundle

        res = import_bundle(store, repo=repo, root=root, context_dir=context_dir)
        for w in res.warnings:
            print(f"warning: {w}", file=out)
        for c in res.conflicts:
            print(f"conflict (skipped): {c}", file=out)
        print(
            f"Imported: {len(res.updated)} updated, {len(res.promoted)} promoted, "
            f"{len(res.conflicts)} conflicts.",
            file=out,
        )
        return 0
    return 1


def _cmd_files(args, out) -> int:
    if args.path:
        base = Path(args.path)
    else:
        # New decisions are proposals: `files new` scaffolds into candidate/;
        # every other subcommand operates on the canonical decisions/ tree.
        status_dir = "candidate" if args.files_command == "new" else "decisions"
        base = resolve_context_dir(".", load_settings().context_dir) / status_dir
    if not base.exists():
        print(f"no such directory: {base}", file=out)
        return 1
    if args.files_command == "lint":
        from metatron.filesfirst.lint import lint_tree
        errors = lint_tree(base)
        for e in errors:
            print(f"{e.path}: {e.message}", file=out)
        if errors:
            print(f"{len(errors)} problem(s) found", file=out)
            return 1
        print("ok", file=out)
        return 0
    if args.files_command == "index":
        from metatron.filesfirst.index import write_index
        path = write_index(base)
        print(str(path), file=out)
        return 0
    if args.files_command == "new":
        target = base / f"{args.slug}.md"
        if target.exists():
            print(f"refusing to overwrite {target}", file=out)
            return 1
        # The OKF concept shape `mirror import` reads: id-less (identity is the
        # filename slug; an id is minted if the repo migrates to the DB index),
        # `type` as the one required field, Pattern/Rationale as the body.
        target.write_text(
            "---\n"
            "type: Metatron Decision\n"
            f"title: {args.title}\n"
            "scope: \n"
            "confidence: medium\n"
            "---\n\n"
            "## Pattern\n\n## Rationale\n",
            encoding="utf-8")
        print(str(target), file=out)
        return 0
    if args.files_command == "record":
        from metatron.gitlog.reader import GitLogReader
        from metatron.filesfirst.document import decision_ids
        from metatron.filesfirst.ledger import append_entries, entries_from_commit
        from metatron.filesfirst.counts import apply_counts
        from metatron.filesfirst.index import write_index

        commits = GitLogReader(args.repo).commits(
            max_commits=args.max_commits, since=args.since)
        entries = [e for c in commits for e in entries_from_commit(c)]
        append_entries(base / "log", entries, known_ids=decision_ids(base))
        apply_counts(base)
        write_index(base)
        print(f"recorded {len(entries)} trailer entr(y/ies)", file=out)
        return 0
    if args.files_command == "report":
        from datetime import date, timedelta
        from metatron.gitlog.reader import GitLogReader
        from metatron.filesfirst.report import (
            build_report, load_decisions, load_window_entries, render_markdown)

        end = args.until or date.today().isoformat()
        start = args.since or (date.today() - timedelta(days=args.days)).isoformat()
        commits = GitLogReader(args.repo).commits(since=start, max_commits=args.max_commits)
        # `--since` is an inclusive lower bound by author date; re-filter to also
        # apply the upper bound `end` (the adoption denominator = commits in window).
        in_window = [c for c in commits if start <= c.date.date().isoformat() <= end]
        report = build_report(
            load_window_entries(base / "log", start, end),
            total_commits=len(in_window),
            decisions=load_decisions(base),
            start=start, end=end)
        markdown = render_markdown(report)
        if args.out:
            Path(args.out).write_text(markdown, encoding="utf-8")
            print(str(args.out), file=out)
        else:
            print(markdown, file=out)
        return 0
    if args.files_command == "check-fields":
        import subprocess
        from metatron.mirror.render import split_frontmatter
        from metatron.filesfirst.fields import changed_fields, ownership_violations
        from metatron.filesfirst.schema import RESERVED_FILENAMES

        repo_path = Path(args.repo).resolve()
        problems = []
        for md in sorted(base.glob("*.md")):
            if md.name in RESERVED_FILENAMES:  # log/ is a subdir, so glob never reaches unmatched.md
                continue
            rel = md.resolve().relative_to(repo_path)
            show = subprocess.run(
                ["git", "show", f"{args.base}:{rel}"],
                cwd=repo_path, capture_output=True, text=True)
            old_fm, _ = split_frontmatter(show.stdout) if show.returncode == 0 else ({}, "")
            new_fm, _ = split_frontmatter(md.read_text(encoding="utf-8"))
            bad = ownership_violations(changed_fields(old_fm, new_fm), actor=args.actor)
            for field_name in sorted(bad):
                problems.append(f"{md}: {args.actor} may not edit '{field_name}'")
        for p in problems:
            print(p, file=out)
        if problems:
            print(f"{len(problems)} field-ownership violation(s)", file=out)
            return 1
        print("ok", file=out)
        return 0
    print("unknown files command", file=out)
    return 2


def _cmd_version_upgrade(out) -> int:
    """Self-upgrade: fresh update check, then run (or print) the install-appropriate
    upgrade command. The command runs only when its provenance is trusted — a
    user-provided METATRON_INSTALL_CMD / install.json entry or an unambiguous
    uv-tool/pipx path signature; the plain-pip fallback is printed instead, since
    running the wrong installer can split one install into two."""
    from metatron.version import check_for_update, run_upgrade, upgrade_plan
    info = check_for_update(force=True)
    if info is None:
        print("update check unavailable (dev build, or METATRON_NO_UPDATE_CHECK set)", file=out)
        return 1
    if not info.latest:
        print("could not reach PyPI to determine the latest version — try again later", file=out)
        return 1
    if not info.available:
        print(f"already up to date (latest on PyPI: {info.latest})", file=out)
        return 0
    plan = upgrade_plan()
    if not plan.confident:
        print(f"update available: {info.current} -> {info.latest}", file=out)
        print("install method could not be determined reliably; run this yourself:", file=out)
        print(f"  {plan.command}", file=out)
        print("(or set METATRON_INSTALL_CMD / edit ~/.metatron/install.json to teach "
              "metatron the right command)", file=out)
        return 1
    print(f"upgrading {info.current} -> {info.latest} via: {plan.command}", file=out)
    rc, output = run_upgrade(plan)
    if output:
        print(output, file=out)
    if rc != 0:
        print(f"upgrade command exited with {rc}", file=out)
        return 1
    print(f"upgraded to {info.latest} — restart any running `metatron serve` to pick it up.",
          file=out)
    return 0


def _cmd_context(args, out) -> int:
    if args.context_command == "setup":
        from metatron.context_setup import run_setup
        target = Path(args.path)
        if not target.is_dir():
            print(f"no such directory: {target}", file=out)
            return 1
        print(f"Onboarding to Metatron (files-first): {target.resolve()}", file=out)
        kb_name = getattr(args, "dir", None)
        try:
            res = run_setup(target, dir_name=kb_name,
                            review_gate=getattr(args, "review_gate", None))
        except ValueError as exc:
            print(str(exc), file=out)
            return 1
        for line in res.messages:
            print(f"  {line}", file=out)
        from metatron.config import DEFAULT_CONTEXT_DIR
        shown = kb_name or load_settings().context_dir or DEFAULT_CONTEXT_DIR
        if res.review_gate == "pr":
            print(f"\nDone (review gate: pr). Author decisions into {shown}/decisions/ on a "
                  "working branch (skill: context-okf-llm-ingest);", file=out)
            print("the human-reviewed pull request that lands them is the curation act.", file=out)
        else:
            print(f"\nDone (review gate: candidates). Author candidates into {shown}/candidate/ "
                  "(skill: context-okf-llm-ingest);", file=out)
            print("promotion is a human-reviewed git mv (skill: context-okf-promote-candidates).", file=out)
        return 0
    print("unknown context command", file=out)
    return 2


def _default_verification_dir() -> Path:
    from metatron.verification.discover import verification_dir
    return verification_dir(".", load_settings().context_dir)


def _cmd_verification(args, out) -> int:
    cmd = getattr(args, "verification_command", None)
    if cmd == "setup":
        from metatron.verification.setup import run_verification_setup
        target = Path(args.path)
        if not target.is_dir():
            print(f"no such directory: {target}", file=out)
            return 1
        print(f"Wiring verification contracts into {target.resolve()}", file=out)
        res = run_verification_setup(
            target, dir_name=args.dir, review_gate=args.review_gate)
        for line in res.messages:
            print(f"  {line}", file=out)
        return 0
    if cmd == "template":
        from metatron.verification.scaffold import template
        print(template(), file=out)
        return 0
    if cmd == "new":
        from metatron.verification.scaffold import scaffold_new
        settings = load_settings()
        gate = settings.review_gate or "pr"
        if args.path:
            target_dir = Path(args.path)
        else:
            kb = resolve_context_dir(".", settings.context_dir)
            target_dir = kb / ("verification" if gate == "pr" else "candidate")
        try:
            path = scaffold_new(target_dir, args.slug, args.scope, args.from_ref)
        except FileExistsError as exc:
            print(f"refusing to overwrite {exc}", file=out)
            return 1
        print(str(path), file=out)
        return 0
    if cmd == "audit":
        from metatron.verification.audit import audit_dir
        base = Path(args.path) if args.path else _default_verification_dir()
        errors = audit_dir(base)
        for e in errors:
            print(f"{e.path}: {e.message}", file=out)
        if errors:
            print(f"{len(errors)} problem(s) found", file=out)
            return 1
        print("ok", file=out)
        return 0
    if cmd == "run":
        return _cmd_verification_run(args, out)
    print("unknown verification command", file=out)
    return 2


def _cmd_verification_run(args, out) -> int:
    from metatron.verification import runner as vrun
    from metatron.verification.discover import iter_contracts, select
    from metatron.verification.report import render

    base = Path(args.path) if args.path else _default_verification_dir()
    if not base.exists():
        print(f"no such directory: {base}", file=out)
        return 1
    tags = [t for t in (args.tags or "").split(",") if t.strip()] or None
    contracts = select(iter_contracts(base), scope=args.scope, tags=tags)
    if not contracts:
        print("no matching contracts", file=out)
        return 0
    if args.dry_run:
        print(vrun.plan(contracts, tags=tags), file=out, end="")
        return 0
    if args.judge:
        # Phase-2 hook: no judge provider is wired yet, so judged invariants are
        # skipped rather than silently passed. Executable checks always run.
        print("note: --judge is phase 2 and no judge provider is configured; "
              "judged invariants are skipped, executable checks still run.", file=out)
    timeout = args.timeout or vrun.DEFAULT_TIMEOUT
    report = vrun.run_contracts(contracts, cwd=".", tags=tags, timeout=timeout)
    rendered = render(report, args.report)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
        print(str(args.out), file=out)
    else:
        print(rendered, file=out)
    return 0 if report.passed else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metatron")
    parser.add_argument(
        "--db",
        default=None,
        help="catalog directory, or a single repo's .db file (single-file mode); "
        "overrides METATRON_DB / metatron.toml for this run",
    )
    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="bootstrap candidate decisions from a repo")
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

    serve_p = sub.add_parser("serve", help="serve one repo's decisions to agents over MCP")
    serve_p.add_argument(
        "--repo",
        default=None,
        help="repo id to serve (defaults to METATRON_REPO, else the current dir's id)",
    )

    repo_p = sub.add_parser("repo", help="inspect and choose the repo commands act on")
    repo_sub = repo_p.add_subparsers(dest="repo_command")
    repo_sub.add_parser("list", help="list repos with their decision counts (the ids serve uses)")
    repo_set_p = repo_sub.add_parser(
        "set", help="persist a default repo (saved to metatron.toml)"
    )
    repo_set_p.add_argument("id", help="the repo id to use by default")
    repo_sub.add_parser("unset", help="clear the persisted default repo")

    ui_p = sub.add_parser("ui", help="launch the local curation web UI")
    ui_p.add_argument(
        "--port", type=int, default=1337, help="starting port (bumps if taken)"
    )
    ui_p.add_argument(
        "--files", action="store_true",
        help="files-first mode: curate the repo's git-tracked OKF bundle; "
             "every edit is a git working-tree change reviewed via your "
             "normal git flow (nothing is committed)")
    ui_p.add_argument(
        "--root", default=".",
        help="repo root for --files mode (default: current directory)")

    version_p = sub.add_parser(
        "version", help="show the installed version and check for updates")
    version_p.add_argument(
        "--upgrade", action="store_true",
        help="upgrade to the latest PyPI release using the detected install method "
             "(uv tool / pipx / METATRON_INSTALL_CMD); prints the command instead "
             "of running it when the install method is ambiguous")

    whoami_p = sub.add_parser(
        "whoami", help="show or set the local identity stamped onto served events"
    )
    whoami_p.add_argument("--set-email", default=None, help="set your email")
    whoami_p.add_argument("--set-name", default=None, help="set your display name")

    triage_p = sub.add_parser(
        "triage", help="run the advisory judge over candidate decisions (does not auto-curate)"
    )
    triage_p.add_argument(
        "--repo", default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    triage_p.add_argument("--limit", type=int, default=None, help="max candidates to judge")

    enrich_p = sub.add_parser(
        "enrich-keywords",
        help="backfill retrieval keywords on canonical decisions that lack them (does not curate)",
    )
    enrich_p.add_argument(
        "--repo", default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    enrich_p.add_argument("--limit", type=int, default=None, help="max decisions to enrich")

    refine_p = sub.add_parser(
        "refine-feedback",
        help="reshape captured agent feedback into structured candidate decisions (Opus)",
    )
    refine_p.add_argument(
        "--repo", default=None,
        help="repo id (defaults to METATRON_REPO, else the current dir's id)",
    )
    refine_p.add_argument("--limit", type=int, default=None, help="max feedback reports to refine")
    refine_p.add_argument(
        "--model", default=None, help=f"override the refiner model (default {REFINE_MODEL})"
    )

    cand = sub.add_parser("candidates", help="review and curate candidate decisions")
    cand_sub = cand.add_subparsers(dest="candidates_command")
    list_p = cand_sub.add_parser("list", help="list candidate decisions")
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

    mirror_p = sub.add_parser(
        "mirror", help="sync decisions to/from a git-tracked markdown bundle"
    )
    mirror_sub = mirror_p.add_subparsers(dest="mirror_command")
    m_sync = mirror_sub.add_parser("sync", help="write decisions to the bundle (DB -> files)")
    m_sync.add_argument("--repo", default=None)
    m_sync.add_argument("--root", default=".", help="repo root that holds the knowledge base")
    m_sync.add_argument("--context-dir", default=None,
                        help="knowledge-base dir name (default: context/, or legacy metatron/)")
    m_sync.add_argument("--okf", action="store_true", help="also emit an OKF bundle index")
    m_import = mirror_sub.add_parser("import", help="apply edited bundle files (files -> DB)")
    m_import.add_argument("--repo", default=None)
    m_import.add_argument("--root", default=".")
    m_import.add_argument("--context-dir", default=None,
                          help="knowledge-base dir name (default: context/, or legacy metatron/)")

    files_p = sub.add_parser("files", help="author, lint, and index git-authoritative decision files")
    files_sub = files_p.add_subparsers(dest="files_command")
    f_lint = files_sub.add_parser("lint", help="validate decision files")
    f_lint.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_index = files_sub.add_parser("index", help="regenerate index.md")
    f_index.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_new = files_sub.add_parser("new", help="scaffold a candidate decision")
    f_new.add_argument("slug")
    f_new.add_argument("--title", required=True)
    f_new.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_record = files_sub.add_parser(
        "record", help="post-merge: append usage trailers to the ledger and roll up counts")
    f_record.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_record.add_argument("--repo", default=".", help="git repo root to read commits from")
    f_record.add_argument("--since", default=None, help="git --since window (e.g. '7 days ago')")
    f_record.add_argument("--max-commits", type=int, default=200)
    f_report = files_sub.add_parser(
        "report", help="render a usage digest (adoption, reuse, drift, curation) over the ledger")
    f_report.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_report.add_argument("--repo", default=".", help="git repo root to count commits from")
    f_report.add_argument("--days", type=int, default=7, help="trailing window length")
    f_report.add_argument("--since", default=None, help="window start (ISO date; overrides --days)")
    f_report.add_argument("--until", default=None, help="window end (ISO date; default today)")
    f_report.add_argument("--out", default=None, help="write markdown here instead of stdout")
    f_report.add_argument(
        "--max-commits", type=int, default=1000,
        help="cap on commits scanned for the window; raise it if a window holds "
             "more commits than this, or the adoption denominator under-counts")
    f_check = files_sub.add_parser(
        "check-fields", help="reject cross-ownership frontmatter edits (human vs CI)")
    f_check.add_argument("--base", required=True, help="git ref to diff against")
    f_check.add_argument("--path", default=None, help="decisions dir (default: <context-dir>/decisions)")
    f_check.add_argument("--repo", default=".")
    f_check.add_argument("--actor", choices=("human", "ci"), default="human")

    context_p = sub.add_parser(
        "context", help="onboard a repo to files-first mode (rule, skills, knowledge base)")
    context_sub = context_p.add_subparsers(dest="context_command")
    c_setup = context_sub.add_parser(
        "setup", help="add the consult-first rule, OKF skills, and knowledge-base scaffold")
    c_setup.add_argument(
        "path", nargs="?", default=".",
        help="repo or monorepo-app directory to onboard (default: current dir)")
    c_setup.add_argument(
        "--dir", default=None,
        help="knowledge-base directory name (default: context, or the configured context_dir)")
    c_setup.add_argument(
        "--review-gate", default=None, choices=("pr", "candidates"),
        help="where humans review agent-authored decisions: 'pr' (default) authors "
             "directly into decisions/ with pull-request review as the gate; "
             "'candidates' stages proposals in candidate/ with promotion as a "
             "separate reviewed git mv. Persisted to metatron.toml; re-running "
             "setup with the other value rewrites the managed artifacts")

    verify_p = sub.add_parser(
        "verification", help="author, lint, and run git-tracked verification contracts")
    verify_sub = verify_p.add_subparsers(dest="verification_command")
    v_setup = verify_sub.add_parser(
        "setup", help="wire the authoring workflow into AGENTS.md + drop a worked example")
    v_setup.add_argument("path", nargs="?", default=".",
                         help="repo directory to onboard (default: current dir)")
    v_setup.add_argument("--dir", default=None,
                         help="knowledge-base directory name (default: configured context_dir)")
    v_setup.add_argument("--review-gate", default=None, choices=("pr", "candidates"),
                         help="where the drafted example lands (default: configured gate)")
    verify_sub.add_parser("template", help="print the canonical contract skeleton")
    v_new = verify_sub.add_parser("new", help="scaffold a draft verification contract")
    v_new.add_argument("slug", help="filename slug for the contract")
    v_new.add_argument("--scope", required=True, help="subsystem the contract binds to")
    v_new.add_argument("--from", dest="from_ref", default=None,
                       help="a candidate/decision path to record as source_ref")
    v_new.add_argument("--path", default=None, help="override the target directory")
    v_audit = verify_sub.add_parser("audit", help="read-only lint of verification contracts")
    v_audit.add_argument("--path", default=None, help="override the contracts directory")
    v_run = verify_sub.add_parser(
        "run", help="execute contracts and report (operator/CI only; never over MCP)")
    v_run.add_argument("--scope", default=None, help="only contracts relevant to this scope")
    v_run.add_argument("--tags", default=None, help="comma-separated check tags to run")
    v_run.add_argument("--report", default="text", choices=("text", "json", "junit"))
    v_run.add_argument("--out", default=None, help="write the report to a file")
    v_run.add_argument("--timeout", type=int, default=None, help="per-step timeout seconds")
    v_run.add_argument("--dry-run", action="store_true",
                       help="print the plan and resolved assertions; execute nothing")
    v_run.add_argument("--judge", action="store_true",
                       help="also evaluate judged invariants (phase 2; requires a provider)")
    v_run.add_argument("--path", default=None, help="override the contracts directory")

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

    import_p = sub.add_parser(
        "import", help="merge another employee's exported DB into this catalog"
    )
    import_p.add_argument("path", help="a per-repo .db file (or a catalog dir) to merge in")

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
