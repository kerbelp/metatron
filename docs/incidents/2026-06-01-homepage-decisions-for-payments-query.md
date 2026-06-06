# Incident: homepage decisions returned for an unrelated payments query

- **Date:** 2026-06-01
- **Surface:** MCP `get_decisions_for_context`
- **Severity:** low (no data loss); trust-relevant (served irrelevant decisions)
- **Status:** diagnosed; precision + ranking fix implemented (see "Resolution")

## Symptom

An agent debugging a payments bug queried:

- **area:** `src/routes/api/order_created, payments table, admin payments panel, review-queue-report email`
- **task:** "Debug why paid $19 purchases (LemonSqueezy order_created) are not
  showing up in admin Payments panel and daily admin email shows 0 purchases"

Metatron returned two **homepage** decisions, both scoped to
`src/components/Home/zones` — completely unrelated to payments/orders/admin.

## Root cause

Two distinct factors. The first explains *why homepage content specifically*;
the second is the real, persistent defect.

### 1. Coverage gap at query time (timing)

The request fired at **15:46**. A bulk-approve of 568 candidates ran at
**15:53** (7 minutes later). All 11 payments/order/webhook-relevant decisions became
canonical *in that bulk run* — so at 15:46 there were **zero** relevant canonical
decisions. `get_decisions_for_context` serves canonical-only, so the retriever had
almost nothing with any token overlap to choose from.

Re-running the same query *after* the approval no longer returns homepage decisions;
they are pushed out by ~20 genuinely route/payment-related decisions.

### 2. The relevance floor is too low (the real bug)

`_relevance` in `metatron/mcp_server/service.py` keeps any decision scoring `> 0`,
and a **single** keyword overlap on a common verb clears that floor:

```
score = scope_score*100 + keyword_overlap*10 + confidence_weight
```

The two homepage decisions matched on exactly one token each — generic English
verbs, not domain terms:

- `"shows"` — "The commit history **shows** a consistent pattern…" ↔ "email **shows** 0 purchases"
- `"showing"` — "rather than **showing** an empty shell" ↔ "are not **showing** up"

Scope score was `0` for both (Home/zones is unrelated to `routes/api/...`). With
`keyword_overlap = 1`, score ≈ 11–13 > 0, so they qualified. `"shows"` /
`"showing"` are effectively stopwords but are not in `_STOPWORDS`.

**The correct contract:** return genuinely relevant decisions, or honestly nothing
("No matching decisions") — never filler. Returning irrelevant decisions is worse than
silence: it wastes the agent's attention and erodes trust in everything else
Metatron serves. At 15:46 the honest answer was genuinely "no matching decisions";
the floor bug is what stopped it from saying so.

## Deferred fix (not yet implemented)

Core problem: **common tokens count as much as rare ones.** `"lemonsqueezy"`
should be a strong signal; `"shows"` should be ~none.

- **Preferred — corpus frequency (IDF-lite):** weight each token by how rare it is
  across the canonical corpus, so a lone common-verb overlap scores as the noise it
  is and a scope-0 decision needs real signal to clear the floor. Self-tuning, no
  hand-maintained wordlist.
- **Cheap alternative:** expand `_STOPWORDS` with generic verbs and require
  scope-match OR ≥2 keyword overlaps to qualify. Simple but brittle, and can drop
  legitimate single rare-token matches.

Either way, add a regression test using this exact query asserting the homepage
decisions are **not** returned (and that a zero-coverage area yields "No matching
decisions"). Owner chose to defer the change; this note preserves the diagnosis.

## Resolution (2026-06-01)

Implemented in `metatron/mcp_server/service.py`. A second real query the next
session exposed a related ranking failure (the agent named four precise paths and
broad-ancestor decisions with zero keyword overlap outranked the decision scoped to the
exact sub-path), so both were fixed together:

- **Area splitting** — `area` is split into individual path candidates; scope is
  matched against the best of them, so naming a precise sub-path is rewarded
  instead of diluted in a comma-joined blob.
- **Specificity-aware scope** — exact / inside-the-area matches outweigh a broad
  ancestor that merely contains the area; siblings (sharing only a parent dir)
  score nothing. This fixed `src/components/Home/zones` getting credit against
  `src/components/SubmitFlow`.
- **IDF keyword weighting** — overlap is weighted by inverse document frequency
  across the repo's canonical decisions, so rare domain terms (`checkout`, `webhook`)
  count and boilerplate (`rather than`, `commit`) counts for ~nothing. No
  hand-maintained verb stoplist.
- **Focused payload** — default page reduced from 20 to 8.

Result on the original payments-ledger decision: rank #127 → #1; the homepage filler
no longer surfaces for this class of query.

**Known residual:** scope still outweighs topical match *within* a named directory
— an off-topic decision sharing the path can outrank an on-topic decision in a directory
the agent did not name. The scope/keyword balance (`_SCOPE_SCALE`) is a tuning knob
left for live feedback.

## Lessons

- "No relevant knowledge" is a feature, not a gap — the honest empty answer must be
  reachable.
- Keyword overlap without term weighting produces confident false positives on
  high-frequency words.
- Coverage timing matters when reasoning about a served result: check whether the
  relevant decisions were canonical *at the moment of the query*.
