"""Tests for the LLM provider interface, prompt loading, and decision extraction."""

import pytest

from metatron.extraction.extractor import ExtractionError, DecisionExtractor
from metatron.extraction.prompts import load_prompt, render
from metatron.extraction.provider import AnthropicProvider, LLMProvider
from metatron.extraction.signals import Counted, ScopeSignals
from metatron.models import Confidence, Origin, SourceRefKind, Status


class FakeProvider(LLMProvider):
    """Returns a canned response and records the prompt it was given."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


_SIGNALS = ScopeSignals(
    scope="metatron/storage",
    file_count=3,
    imports=[Counted(name="sqlite3", count=3)],
    bases=[Counted(name="DecisionStore", count=2)],
    commit_count=4,
    fix_count=1,
    subjects=["fix: handle missing db"],
)

_ONE_DECISION = """
[{"pattern": "Access the DB only through DecisionStore",
  "scope": "metatron/storage",
  "rationale": "Keeps SQL contained and storage swappable",
  "confidence": "high"}]
"""


# --- provider interface -------------------------------------------------

def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_anthropic_provider_is_an_llm_provider_and_keeps_its_model():
    provider = AnthropicProvider(model="claude-x", api_key="unused-in-this-test")
    assert isinstance(provider, LLMProvider)
    assert provider.model == "claude-x"


# --- prompt template ----------------------------------------------------

def test_load_prompt_returns_an_editable_template_with_placeholders():
    template = load_prompt("extract_decisions")
    assert "{scope}" in template
    assert "{signals}" in template


def test_render_substitutes_placeholders():
    assert render("a {x} b", x="Z") == "a Z b"


# --- extraction ---------------------------------------------------------

def test_extract_parses_decisions_from_provider_json():
    decisions = DecisionExtractor(FakeProvider(_ONE_DECISION), "github.com/acme/app").extract(_SIGNALS)

    assert len(decisions) == 1
    p = decisions[0]
    assert p.pattern == "Access the DB only through DecisionStore"
    assert p.confidence is Confidence.HIGH


def test_extracted_decisions_are_uncurated_bootstrap_with_provenance():
    p = DecisionExtractor(FakeProvider(_ONE_DECISION), "github.com/acme/app").extract(_SIGNALS)[0]
    assert p.status is Status.CANDIDATE
    assert p.origin is Origin.BOOTSTRAP
    assert p.repo == "github.com/acme/app"
    assert any(
        ref.kind is SourceRefKind.FILE and ref.ref == "metatron/storage"
        for ref in p.source_refs
    )


def test_extracted_decisions_record_the_model():
    p = DecisionExtractor(
        FakeProvider(_ONE_DECISION), "github.com/acme/app", model="claude-sonnet-4-6"
    ).extract(_SIGNALS)[0]
    assert p.model == "claude-sonnet-4-6"


def test_extract_includes_scope_and_signals_in_the_prompt():
    provider = FakeProvider(_ONE_DECISION)
    DecisionExtractor(provider, "github.com/acme/app").extract(_SIGNALS)
    assert "metatron/storage" in provider.last_prompt
    assert "sqlite3" in provider.last_prompt


def test_extract_handles_json_wrapped_in_markdown_fences():
    fenced = "```json\n" + _ONE_DECISION.strip() + "\n```"
    decisions = DecisionExtractor(FakeProvider(fenced), "github.com/acme/app").extract(_SIGNALS)
    assert len(decisions) == 1


def test_extract_defaults_unknown_confidence_to_medium():
    response = '[{"pattern": "p", "rationale": "r", "confidence": "wat"}]'
    p = DecisionExtractor(FakeProvider(response), "github.com/acme/app").extract(_SIGNALS)[0]
    assert p.confidence is Confidence.MEDIUM


def test_extract_returns_empty_list_for_empty_array():
    assert DecisionExtractor(FakeProvider("[]"), "github.com/acme/app").extract(_SIGNALS) == []


def test_extract_raises_on_malformed_json():
    with pytest.raises(ExtractionError):
        DecisionExtractor(FakeProvider("not json at all"), "github.com/acme/app").extract(_SIGNALS)
