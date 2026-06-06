"""Tests for the Decision data model and its enums."""

from metatron.models import (
    Confidence,
    Origin,
    Decision,
    SourceRef,
    SourceRefKind,
    Status,
)


def _minimal_decision(**overrides) -> Decision:
    fields = dict(
        repo="github.com/acme/app",
        pattern="Use the repository pattern for DB access",
        scope="metatron/storage",
        rationale="Keeps SQL out of callers and storage swappable",
        origin=Origin.BOOTSTRAP,
    )
    fields.update(overrides)
    return Decision(**fields)


def test_decision_defaults_to_candidate_status():
    # Core principle: nothing is canonical without curation.
    decision = _minimal_decision()
    assert decision.status is Status.CANDIDATE


def test_decision_generates_unique_ids():
    a = _minimal_decision()
    b = _minimal_decision()
    assert a.id and b.id
    assert a.id != b.id


def test_decision_requires_origin():
    # Provenance is mandatory — a decision must say where it came from.
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Decision(
            pattern="x",
            scope="y",
            rationale="z",
        )  # type: ignore[call-arg]


def test_decision_defaults_confidence_to_medium():
    assert _minimal_decision().confidence is Confidence.MEDIUM


def test_decision_sets_created_and_updated_timestamps():
    decision = _minimal_decision()
    assert decision.created_at is not None
    assert decision.updated_at is not None


def test_source_ref_carries_kind_and_ref():
    ref = SourceRef(kind=SourceRefKind.COMMIT, ref="abc123", detail="introduced here")
    assert ref.kind is SourceRefKind.COMMIT
    assert ref.ref == "abc123"
    assert ref.detail == "introduced here"


def test_enum_values_are_lowercase_strings():
    assert Status.CANONICAL.value == "canonical"
    assert Origin.AGENT_SUBMITTED.value == "agent_submitted"
    assert Confidence.HIGH.value == "high"
    assert SourceRefKind.FILE.value == "file"
