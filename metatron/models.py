"""Structured records for decisions.

A *decision* is a captured implementation decision — a prescriptive pattern, the
scope it applies to, why it holds, and where it came from. Decisions are always
structured records (never prose) and always start life as ``candidate``: nothing
becomes ``canonical`` without human curation.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from metatron.version import current_version


class Confidence(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Status(str, enum.Enum):
    CANDIDATE = "candidate"
    CANONICAL = "canonical"
    REJECTED = "rejected"


class Origin(str, enum.Enum):
    BOOTSTRAP = "bootstrap"
    AGENT_SUBMITTED = "agent_submitted"
    AGENT_FEEDBACK = "agent_feedback"  # born from a "what was missing" feedback report


class SourceRefKind(str, enum.Enum):
    FILE = "file"
    COMMIT = "commit"


class TriageVerdict(str, enum.Enum):
    """A judge pass's recommendation to the human curator. Advisory only."""

    NONE = "none"          # not yet triaged
    APPROVE = "approve"    # clearly a useful canonical convention
    BORDERLINE = "borderline"
    REJECT = "reject"      # vague / generic / framework-restating / unsupported


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceRef(BaseModel):
    """Provenance for a decision: a file path or a commit SHA, plus context."""

    kind: SourceRefKind
    ref: str
    detail: str = ""


class IngestRun(BaseModel):
    """Telemetry for one ingest run — powers the one-time cost view."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str
    model: str
    timestamp: datetime = Field(default_factory=_now)
    files_parsed: int = 0
    commits_read: int = 0
    scopes: int = 0
    decisions_created: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Decision(BaseModel):
    """A single structured decision."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str  # stable repo identity (normalized git remote) — see repo_identity
    pattern: str
    scope: str
    rationale: str
    origin: Origin
    confidence: Confidence = Confidence.MEDIUM
    model: str = ""  # the model that extracted it ("" for agent-submitted decisions)
    created_version: str = Field(default_factory=current_version)  # build that created it
    source_refs: list[SourceRef] = Field(default_factory=list)
    status: Status = Status.CANDIDATE
    triage: TriageVerdict = TriageVerdict.NONE  # advisory judge recommendation
    triage_reason: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
