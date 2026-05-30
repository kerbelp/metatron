"""Tests for the Prior data model and its enums."""

from metatron.models import (
    Confidence,
    Origin,
    Prior,
    SourceRef,
    SourceRefKind,
    Status,
)


def _minimal_prior(**overrides) -> Prior:
    fields = dict(
        pattern="Use the repository pattern for DB access",
        scope="metatron/storage",
        rationale="Keeps SQL out of callers and storage swappable",
        origin=Origin.BOOTSTRAP,
    )
    fields.update(overrides)
    return Prior(**fields)


def test_prior_defaults_to_candidate_status():
    # Core principle: nothing is canonical without curation.
    prior = _minimal_prior()
    assert prior.status is Status.CANDIDATE


def test_prior_generates_unique_ids():
    a = _minimal_prior()
    b = _minimal_prior()
    assert a.id and b.id
    assert a.id != b.id


def test_prior_requires_origin():
    # Provenance is mandatory — a prior must say where it came from.
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Prior(
            pattern="x",
            scope="y",
            rationale="z",
        )  # type: ignore[call-arg]


def test_prior_defaults_confidence_to_medium():
    assert _minimal_prior().confidence is Confidence.MEDIUM


def test_prior_sets_created_and_updated_timestamps():
    prior = _minimal_prior()
    assert prior.created_at is not None
    assert prior.updated_at is not None


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
