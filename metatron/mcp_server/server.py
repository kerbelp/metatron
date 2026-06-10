"""The MCP server: a thin FastMCP wrapper over the service logic.

Exposes the two milestone tools over MCP (stdio transport for local agent
integration). All real behaviour lives in :mod:`metatron.mcp_server.service`;
this module only declares the tools and wires them to a store.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from metatron.events import Event, EventKind
from metatron.feedback_score import helpfulness_scores
from metatron.identity import Identity
from metatron.mcp_server import service
from metatron.storage.base import EventStore, DecisionStore
from metatron.version import current_version


def build_server(
    store: DecisionStore,
    repo: str,
    event_store: EventStore | None = None,
    identity: Identity | None = None,
) -> FastMCP:
    """Build an MCP server bound to a single ``repo`` (agents see only its decisions).

    ``identity`` is the local employee running this server; when provided, every
    recorded event is stamped with it so feedback/queries are attributable.
    """
    server = FastMCP("metatron")

    def _record(event: Event) -> None:
        if event_store is None:
            return
        if identity is not None:
            # Stamp who produced this event (the agent never sends it).
            event.actor_id = identity.actor_id
            event.actor_email = identity.email
            event.actor_name = identity.display_name
        event_store.record(event)

    def _helpfulness() -> dict[str, float]:
        # Centered helpfulness signal per decision, from this repo's feedback ratings.
        # Empty when there's no event store yet — serving then falls back to pure
        # scope/keyword ranking, exactly as before this feature.
        if event_store is None:
            return {}
        scores = helpfulness_scores(event_store.list_events(repo=repo))
        return {pid: s.centered for pid, s in scores.items()}

    @server.tool()
    def get_decisions_for_context(
        file_path_or_area: Annotated[
            str,
            Field(description=(
                "The file path, directory, or architectural area you are about to work in "
                '(e.g. "src/routes/api/users.py" or "billing").'
            )),
        ],
        task_description: Annotated[
            str,
            Field(description=(
                "A short description of what you are about to do there "
                '(e.g. "add error handling to the billing webhook").'
            )),
        ],
    ) -> str:
        """Fetch the team's canonical engineering decisions for a file/area and task.

        Call this FIRST, before writing or editing code in an area — and again when you
        move to a new file or module. It surfaces the conventions, preferred patterns,
        rejected approaches, and known gotchas the team has already curated for that part
        of the codebase, so you write code that matches their standards on the first try
        instead of rediscovering them. Read the returned decisions and comply with them.

        Behavior: only human-approved (canonical) decisions are returned, ranked by how
        well their scope matches `file_path_or_area` and by how helpful past agents
        rated them. Each call also records a usage event so your later `submit_feedback`
        can be tied back to this exact result set.

        Returns a plain-text block. The first line is a header carrying the query token
        and server revision; then each decision is numbered for rating by index, e.g.:

            metatron:query 7f3a... · rev 0.2.1 (reference the query id in submit_feedback)
            [1] [high] Use internal.http for outbound calls, not the requests library
              scope: src/services/**
              why: flaky network caused phantom 5xx errors; the internal client retries

        Keep the query token: pass it to `submit_feedback` after the task to rate the
        decisions by their `[index]`. If nothing is registered for the area, the body is
        exactly "No matching decisions." — proceed normally.
        """
        decisions = service.get_decisions_for_context(
            store, repo, file_path_or_area, task_description,
            helpfulness=_helpfulness(),
        )
        # Record the query first so its id can be surfaced as the feedback token;
        # the token is only meaningful (resolvable) when events are persisted.
        event = Event(
            repo=repo,
            kind=EventKind.QUERY,
            area=file_path_or_area,
            task=task_description,
            result_count=len(decisions),
            decision_ids=[p.id for p in decisions],
        )
        _record(event)
        return service.format_decisions(
            decisions,
            query_id=event.id if event_store is not None else None,
            version=current_version(),
        )

    @server.tool()
    def submit_feedback(
        query_id: Annotated[
            str,
            Field(description="The `query_id` token from the get_decisions_for_context output you are responding to."),
        ] = "",
        helpful: Annotated[
            list[int] | None,
            Field(description="Optional shorthand: 1-based indices of decisions that helped. Usually derived from `ratings`, so prefer `ratings`."),
        ] = None,
        unhelpful: Annotated[
            list[int] | None,
            Field(description="Optional shorthand: 1-based indices of decisions that were noise or misleading."),
        ] = None,
        ratings: Annotated[
            dict[str, int] | None,
            Field(description='The main signal: map of 1-based decision index (as a string) to a helpfulness score 1-10, where 10 = exactly right and 1 = misleading (e.g. {"1": 9, "2": 3}).'),
        ] = None,
        what_was_missing: Annotated[
            str,
            Field(description="A convention Metatron should have known for this task but didn't. Captured as a candidate for human curation."),
        ] = "",
        missing_scope: Annotated[
            str,
            Field(description="Optional file path or area the missing convention applies to."),
        ] = "",
    ) -> str:
        """Report how helpful the served decisions were, and what was missing.

        Call this after a task where you used Metatron's decisions. Reference the
        `query_id` from the get_decisions_for_context output, then — most useful of all
        — **rate each served decision 1-10 by its [index]** in `ratings`, where 10 means
        it was exactly right and 1 means it was misleading. Also state any convention
        Metatron should have known but didn't, in `what_was_missing`.

        Behavior: ratings are 1-based indices into the decisions the named query served
        (they map to real decision ids locally, so you never echo a UUID; unknown indices
        and out-of-range scores are dropped). The graded scores feed a time-decayed,
        shrunk helpfulness signal that reorders which decisions get served first next
        time — helpful ones rise, misleading ones sink. A `what_was_missing` report is
        stored as a gap for a human-gated refiner to later reshape into a CANDIDATE
        decision. Nothing you send here promotes, demotes, or rejects a decision, or changes
        its wording — crossing the canonical set is always a human's call.

        Returns a short text confirmation that the feedback was recorded (and notes
        when a gap was captured for curation).
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
            msg += " The gap will be refined into structured decisions for curation."
        return msg

    @server.tool()
    def submit_candidate_decision(
        pattern: Annotated[
            str,
            Field(description=(
                'The concrete rule or guideline, stated imperatively '
                '(e.g. "Use internal.http for outbound calls, not the requests library").'
            )),
        ],
        scope: Annotated[
            str,
            Field(description=(
                'Where the rule applies: a file path, directory/glob, or architectural layer '
                '(e.g. "src/services/**"), or "global".'
            )),
        ],
        rationale: Annotated[
            str,
            Field(description=(
                "Why the convention exists — the problem or bug it prevents "
                '(e.g. "flaky network caused phantom 5xx errors; the internal client retries").'
            )),
        ],
        confidence: Annotated[
            Literal["low", "medium", "high"],
            Field(description="How strongly the team holds this convention."),
        ] = "medium",
        keywords: Annotated[
            list[str] | None,
            Field(description=(
                "Optional: 3-8 retrieval terms an engineer might use when describing a "
                "task this rule applies to — synonyms and code identifiers not already "
                'in the pattern wording (e.g. ["s3", "presigned", "upload"]).'
            )),
        ] = None,
    ) -> str:
        """Record a new engineering convention you discovered while working — for human review.

        Call this when you find an undocumented convention, a tricky gotcha, or a preferred
        pattern that Metatron did not already know but future agents should. It is stored as
        an uncurated CANDIDATE: a human maintainer must approve it in the Metatron UI or CLI
        before it becomes canonical and is served to other agents. Nothing you submit here is
        auto-promoted.

        Returns the new candidate decision's id. If the pattern near-duplicates a decision
        already on record (in any wording), nothing new is stored and the existing
        decision's id is returned with a note — no need to resubmit known conventions.
        """
        duplicate = service.find_duplicate(store, repo=repo, pattern=pattern)
        if duplicate is not None:
            return (
                f"Already on record as decision {duplicate.id} "
                f"(status: {duplicate.status.value}) — not stored again."
            )
        decision = service.submit_candidate_decision(
            store,
            repo=repo,
            pattern=pattern,
            scope=scope,
            rationale=rationale,
            confidence=confidence,
            keywords=keywords,
        )
        _record(Event(repo=repo, kind=EventKind.SUBMIT, area=scope, decision_ids=[decision.id]))
        return decision.id

    return server
