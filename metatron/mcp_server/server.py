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


def build_server(store: PriorStore, event_store: EventStore | None = None) -> FastMCP:
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
            store, file_path_or_area, task_description
        )
        _record(
            Event(
                kind=EventKind.QUERY,
                area=file_path_or_area,
                task=task_description,
                result_count=len(priors),
                prior_ids=[p.id for p in priors],
            )
        )
        return service.format_priors(priors)

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
            pattern=pattern,
            scope=scope,
            rationale=rationale,
            confidence=confidence,
        )
        _record(Event(kind=EventKind.SUBMIT, area=scope, prior_ids=[prior.id]))
        return prior.id

    return server
