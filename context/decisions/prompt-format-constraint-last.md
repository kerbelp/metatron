---
type: Metatron Decision
scope: metatron/extraction
confidence: medium
source_refs:
  - metatron/extraction/prompts.py
---

## Pattern
When composing LLM prompts from a template plus appended directives (e.g. an
output-language directive), the output-format constraint ("return only the JSON
array, no prose outside it") must come last in the assembled prompt. Any
directive appended after the template restates the format constraint at the end.

## Rationale
Models weight the final instruction heavily; an appended directive that trails
the format constraint caused prose-wrapped JSON that broke parsing. Restating
the constraint last keeps extraction output machine-readable regardless of
which directives are appended.
