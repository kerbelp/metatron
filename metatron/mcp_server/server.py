"""The MCP server: a thin FastMCP wrapper over the service logic.

Exposes the two milestone tools over MCP (stdio transport for local agent
integration). All real behaviour lives in :mod:`metatron.mcp_server.service`;
this module only declares the tools and wires them to a store.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from metatron.events import Event, EventKind
from metatron.mcp_server import service
from metatron.storage.base import EventStore, PriorStore
from metatron.version import current_version


def build_server(
    store: PriorStore, repo: str, event_store: EventStore | None = None
) -> FastMCP:
    """Build an MCP server bound to a single ``repo`` (agents see only its priors)."""
    server = FastMCP("metatron")

    def _record(event: Event) -> None:
        if event_store is not None:
            event_store.record(event)

    @server.tool()
    def get_priors_for_context(file_path_or_area: str, task_description: str) -> str:
        """Return the canonical priors relevant to an area and task.

        Args:
            file_path_or_area: a file path or directory/area in the codebase.
            task_description: what the agent is about to do there.
        """
        priors = service.get_priors_for_context(
            store, repo, file_path_or_area, task_description
        )
        # Record the query first so its id can be surfaced as the feedback token;
        # the token is only meaningful (resolvable) when events are persisted.
        event = Event(
            repo=repo,
            kind=EventKind.QUERY,
            area=file_path_or_area,
            task=task_description,
            result_count=len(priors),
            prior_ids=[p.id for p in priors],
        )
        _record(event)
        return service.format_priors(
            priors,
            query_id=event.id if event_store is not None else None,
            version=current_version(),
        )

    @server.tool()
    def submit_feedback(
        query_id: str = "",
        helpful: list[int] | None = None,
        unhelpful: list[int] | None = None,
        ratings: dict[str, int] | None = None,
        what_was_missing: str = "",
        missing_scope: str = "",
    ) -> str:
        """Report how helpful the served priors were, and what was missing.

        Call this after a task where you used Metatron's priors. Reference the
        `query_id` from the get_priors_for_context output, then — most useful of all
        — **rate each served prior 1-10 by its [index]** in `ratings`, where 10 means
        it was exactly right and 1 means it was misleading. Also state any convention
        Metatron should have known but didn't, in `what_was_missing`.

        Your ratings directly tune which priors get served first next time: helpful
        ones rise, misleading ones sink. A gap report becomes a CANDIDATE prior for
        human curation. Nothing you send here promotes, demotes, or rejects a prior —
        crossing the canonical set is always a human's call.

        Args:
            query_id: the token from the priors output you are responding to.
            ratings: map of 1-based prior index -> helpfulness 1-10 (e.g. {"1": 9, "2": 3}).
            helpful: 1-based indices that helped (optional shorthand; derived from ratings).
            unhelpful: 1-based indices that were noise (optional shorthand).
            what_was_missing: a convention Metatron should have had.
            missing_scope: optional scope (path) for that convention.
        """
        if event_store is None:
            return "Feedback unavailable: this server has no event store."
        service.submit_feedback(
            store,
            event_store,
            repo=repo,
            query_id=query_id,
            helpful=helpful or [],
            unhelpful=unhelpful or [],
            ratings=ratings or {},
            what_was_missing=what_was_missing,
            missing_scope=missing_scope,
        )
        msg = f"Thanks — feedback recorded (rev {current_version()})."
        if what_was_missing.strip():
            msg += " The gap will be refined into structured priors for curation."
        return msg

    @server.tool()
    def submit_candidate_learning(
        pattern: str,
        scope: str,
        rationale: str,
        confidence: str = "medium",
    ) -> str:
        """Submit a candidate prior learned in practice.

        Stored as an uncurated candidate; it does NOT enter the canonical set.
        Returns the new prior's id.
        """
        prior = service.submit_candidate_learning(
            store,
            repo=repo,
            pattern=pattern,
            scope=scope,
            rationale=rationale,
            confidence=confidence,
        )
        _record(Event(repo=repo, kind=EventKind.SUBMIT, area=scope, prior_ids=[prior.id]))
        return prior.id

    return server
