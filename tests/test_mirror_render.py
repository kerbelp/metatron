from metatron.models import Decision, Origin, Confidence, SourceRef, SourceRefKind, Status
from metatron.mirror.render import (
    render_document, parse_document, fingerprint_decision, fingerprint_fields,
)


def _decision(**kw):
    base = dict(repo="github.com/acme/app", pattern="Use zod at API boundaries",
                scope="web/api", rationale="Hand-rolled validation drifts.",
                origin=Origin.AGENT_SUBMITTED, confidence=Confidence.MEDIUM,
                keywords=["zod", "validation"],
                source_refs=[SourceRef(kind=SourceRefKind.FILE, ref="src/api/validate.ts:42")])
    base.update(kw)
    return Decision(**base)


def test_render_emits_okf_type_field():
    text = render_document(_decision(), helpfulness=None)
    assert "type: Metatron Decision" in text  # required OKF v0.1 concept field


def test_render_includes_human_fields_in_frontmatter_and_body():
    text = render_document(_decision(), helpfulness=None)
    assert "id:" in text and "confidence: medium" in text
    assert "Use zod at API boundaries" in text          # pattern in body
    assert "Hand-rolled validation drifts." in text     # rationale in body
    assert "src/api/validate.ts:42" in text             # source_refs


def test_render_marks_machine_fields_readonly():
    text = render_document(_decision(), helpfulness=None)
    assert "keywords:" in text
    assert "read-only" in text.lower()


def test_parse_returns_human_fields_only():
    text = render_document(_decision(), helpfulness=None)
    parsed = parse_document(text)
    assert parsed["id"]                      # identity preserved
    assert parsed["scope"] == "web/api"
    assert parsed["confidence"] == "medium"
    assert parsed["pattern"] == "Use zod at API boundaries"
    assert parsed["rationale"].startswith("Hand-rolled")
    # machine-owned fields are NOT returned as editable
    assert "keywords" not in parsed
    assert "helpfulness_score" not in parsed
    assert "updated_at" not in parsed


def test_render_then_parse_preserves_human_fields():
    d = _decision()
    parsed = parse_document(render_document(d, helpfulness=None))
    assert parsed["id"] == d.id
    assert parsed["scope"] == d.scope
    assert parsed["pattern"] == d.pattern
    assert parsed["rationale"] == d.rationale


def test_fingerprint_matches_between_decision_and_its_parsed_file():
    d = _decision()
    assert d.status == Status.CANDIDATE  # Decision default
    parsed = parse_document(render_document(d, helpfulness=None))
    assert fingerprint_decision(d) == fingerprint_fields(parsed, Status.CANDIDATE)
