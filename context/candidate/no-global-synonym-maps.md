---
type: Metatron Decision
scope: metatron/mcp_server
confidence: high
source_refs:
  - metatron/mcp_server/service.py
  - metatron/models.py
---

## Pattern
Retrieval relevance comes from per-decision `keywords` (LLM-generated at
authoring/enrichment time) plus IDF weighting over the repo's own canonical
decisions — never from a global synonym/alias table. Do not reintroduce shared
keyword-expansion maps, hardcoded stopword-style boosts for specific domains,
or any cross-repo vocabulary.

## Rationale
A global alias table was built and then deliberately retired: it encoded one
codebase's vocabulary into every deployment, aged badly, and its maintenance
cost grew with every domain. Per-decision keywords keep the vocabulary local to
the repo that owns it, and IDF makes rare domain terms count without any
curated list.
