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


class EventKind(str, enum.Enum):
    QUERY = "query"    # get_priors_for_context was called
    SUBMIT = "submit"  # submit_candidate_learning was called


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
