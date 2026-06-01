# Design: feedback → structured priors (Opus refinement, human-gated)

- **Date:** 2026-06-01
- **Status:** approved (capture-only confirmed)
- **Builds on:** the feedback loop (`2026-06-01-feedback-loop.md`). Refines feature B;
  **not** the deferred auto-loop (C) — Opus creates *candidates*, never canonical.

## Why

Raw `what_was_missing` feedback is high-signal but arrives as a prose blob (one gap
often bundles several conventions). Priors must be **structured records, not prose**.
So instead of `submit_feedback` dumping the blob into the queue, an LLM pass reshapes
each gap into clean, split, structured candidates — periodically, idempotently, with
the human curation gate intact.

## Flow

```
submit_feedback  → records a FEEDBACK event (gap text, handled=false)   [capture only]
metatron refine-feedback (run periodically)
   → Opus 4.8 reshapes each UNHANDLED gap into 1..N structured candidates
     (crisp pattern / scope / rationale; splits distinct conventions)
   → adds them as candidates (origin=agent_feedback)
   → marks the feedback handled (records produced candidate ids)  [idempotent]
   → human curates candidates → canonical
```

## Changes

- **Capture-only `submit_feedback`:** no longer creates a candidate. It records the
  FEEDBACK event with the gap text (`missing`), the scope hint in `area`, ratings,
  and `handled=False`. (Decided: keeps the queue structured-only.)
- **`Event.handled: bool`** (additive, `_ensure_column`). `EventStore` gains
  `unhandled_feedback(repo=None)` and `mark_handled(event_id, produced_ids)` (sets
  `handled=True` and records the produced candidate ids on the event for provenance).
- **`FeedbackRefiner`** + editable prompt `prompts/refine_feedback.txt` (same shape as
  the extractor/triage): given gap text + scope hint, returns structured priors. Tasked
  to split distinct conventions and keep each pattern prescriptive (not prose).
- **CLI `metatron refine-feedback [--repo] [--limit] [--model]`** — fetch unhandled
  feedback → refine → add candidates → mark handled → print summary + cost. **Defaults
  to `claude-opus-4-8`** (overridable), even though the global default model is Sonnet:
  reshaping is higher-stakes than extraction.
- **Queue provenance:** refined candidates keep `origin=agent_feedback`, so the UI's
  existing origin badge shows **"feedback"** (shipped). No further UI change required.

## Human gate (unchanged principle)

Opus creates **candidates only**; nothing it produces is canonical. This is the same
gate extraction already uses — so it stays on the safe side of the deferred auto-loop
(C). Ratings still never mutate priors.

## Migration of existing data

The 2 feedback events already captured produced *raw prose* candidates under the old
behavior. After shipping: reject those 2 raw candidates and let `refine-feedback`
reprocess the 2 (still `handled=False`) feedback events into structured candidates.

## Testing (TDD)

- `submit_feedback` records a FEEDBACK event (handled=False, gap text + scope) and
  creates **no** candidate.
- `EventStore.unhandled_feedback` returns only unhandled FEEDBACK events; `mark_handled`
  flips the flag and records produced ids; handled events are excluded next time.
- `FeedbackRefiner` parses an LLM response into ≥1 structured priors (origin=agent_feedback,
  status=candidate); splits multiple; tolerates fenced/garbled JSON.
- `refine_feedback` end-to-end (fake provider): unhandled gaps → N candidates, events
  marked handled, re-run is a no-op.
- CLI wires it with the Opus default and prints a cost line.

## Phasing

1. Storage + capture-only `submit_feedback` (+ migrate existing tests).
2. `FeedbackRefiner` + prompt + `refine_feedback` service + `refine-feedback` CLI.
