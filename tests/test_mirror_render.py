from metatron.models import Decision, Origin, Confidence, SourceRef, SourceRefKind
from metatron.mirror.render import render_document


def _decision(**kw):
    base = dict(repo="github.com/acme/app", pattern="Use zod at API boundaries",
                scope="web/api", rationale="Hand-rolled validation drifts.",
                origin=Origin.AGENT_SUBMITTED, confidence=Confidence.MEDIUM,
                keywords=["zod", "validation"],
                source_refs=[SourceRef(kind=SourceRefKind.FILE, ref="src/api/validate.ts:42")])
    base.update(kw); return Decision(**base)


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
