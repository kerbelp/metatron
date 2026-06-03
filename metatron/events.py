"""Usage events — a record of how the priors are being used over MCP.

These capture *usage only* (who asked, what for, how much we returned), so we can
show whether Metatron is being consulted and how well it covers what agents ask.
No token accounting and no helpfulness judgments are recorded here.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from metatron.version import current_version


class EventKind(str, enum.Enum):
    QUERY = "query"        # get_priors_for_context was called
    SUBMIT = "submit"      # submit_candidate_learning was called
    FEEDBACK = "feedback"  # submit_feedback was called (ratings + what-was-missing)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_now)
    repo: str  # stable repo identity the event pertains to
    kind: EventKind
    area: str = ""              # the file_path_or_area queried/submitted against
    task: str = ""              # the task_description, for queries
    result_count: int = 0       # priors returned (queries) — 0 means a "miss"
    prior_ids: list[str] = Field(default_factory=list)
    version: str = Field(default_factory=current_version)  # build that produced the event
    # Feedback events only:
    query_ref: str = ""                  # the QUERY event this feedback responds to
    helpful_prior_ids: list[str] = Field(default_factory=list)
    unhelpful_prior_ids: list[str] = Field(default_factory=list)
    # Graded helpfulness: prior_id -> score 1..10 (resolved from 1-based indices at
    # capture). Powers the time-decayed helpfulness score that auto-weights serve
    # ordering — see metatron/feedback_score.py. binary helpful/unhelpful above are
    # derived from these when an agent rates but omits the binary lists.
    ratings: dict[str, int] = Field(default_factory=dict)
    missing: str = ""                    # "what was missing" — refined into priors later
    handled: bool = False                # feedback: refined into candidates yet?
