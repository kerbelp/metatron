---
type: Metatron Decision
scope: metatron/extraction
confidence: high
source_refs:
  - metatron/extraction/signals.py
  - metatron/extraction/extractor.py
---

## Pattern
Extraction sends only *structural* signals to the LLM — recurring imports,
decorators, base classes, churn/fix/revert counts, and commit subjects — never
raw source code. The deterministic signal-building half (`signals.py`) stays
pure (parsed inputs in, signal bundles out) and separate from the LLM half.

## Rationale
Metatron runs against private codebases with an assumed on-prem posture;
"your source never leaves the machine" is a stated privacy guarantee, not an
implementation detail. The pure/LLM split also keeps both halves independently
testable.
