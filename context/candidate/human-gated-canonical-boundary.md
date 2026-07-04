---
type: Metatron Decision
scope: metatron
confidence: high
source_refs:
  - CLAUDE.md
  - metatron/mcp_server/service.py
  - metatron/feedback_score.py
---

## Pattern
No code path may promote, demote, or reject a decision automatically. Crossing
the canonical boundary is always a human act: `candidates approve` in the CLI,
the curation UI, or (files-first) a human-reviewed `git mv` from
`context/candidate/` to `context/decisions/`. Agent feedback ratings may only
reorder serving *within* a relevance tier — they must never change a decision's
status or let it jump a tier.

## Rationale
This is the product's core invariant: teams trust the canonical set precisely
because every entry was human-approved. The bounded feedback loop
(`feedback_score.py`) was deliberately designed to stop short of the boundary —
weakening it in any feature, however convenient, breaks the trust model.
