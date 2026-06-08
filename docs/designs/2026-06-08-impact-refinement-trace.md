# Refinement-to-serve trace in the Agent Impact view

2026-06-08

## Problem

The Agent Impact view renders a constellation of engineers around Metatron:
decisions flow out (served) and feedback flows back in. These flows are shown
**per engineer, in aggregate** — you can see that an engineer received decisions
and that another sent feedback, but you cannot see the single most compelling
relationship in the data: *one engineer's feedback became a decision that was then
served to a different engineer.*

That lineage already exists in the event log; it is simply not surfaced.

## What the data already gives us

No schema change is required. The forward link is persisted today:

- When a feedback event is refined into candidate decisions, `mark_handled`
  stamps the **feedback event** with the ids of the decisions it produced
  (`Event.decision_ids`, `handled=True`). The event also carries the actor who
  sent the feedback (`actor_id` / `actor_name`).
- A `QUERY` event records the decision ids that were **served** to its actor
  (`Event.decision_ids`).

So for any decision served to engineer B, we can scan handled feedback events for
the one whose produced set contains that decision, and recover the originating
engineer A. That is the `A -> refined decision -> B` chain.

This is read-only provenance display. It does **not** touch the canonical
boundary, auto-promote, or mutate any decision — it only reports a relationship
that the event log already records.

## Design

### Backend

`agent_activity()` gains a `traces` field in its response:

```
traces: [
  { from, from_name, to, to_name, decision_id, pattern, missing }
]
```

Computed from the same windowed events the view already loads:

1. Build a map `produced_decision_id -> originating feedback event` from handled
   feedback events in the window (each contributes its `decision_ids`).
2. Scan `QUERY` events in the window. For each served decision id that appears in
   that map, emit a trace from the feedback's actor (A) to the query's actor (B).
3. Skip self-traces (A == B) and de-duplicate on `(from, to, decision_id)`.

Actor keys are derived exactly as the agent grouping derives them
(`actor_id or actor_email or "anonymous"`), so trace endpoints line up with the
constellation's node ids.

### Frontend

`AgentConstellation` receives `data.traces`. The view already auto-cycles focus
across nodes. When the focused node (B) is the target of a trace:

- The originating node (A) and target node (B) conduits are highlighted as a
  single linked path through the center, distinct from the ambient per-conduit
  particles.
- The refined decision node briefly pulses and carries a small **Refined** tag.
- A caption names the relationship, e.g. *"Refined from Maya's feedback · served
  to Daniel."*

If A is outside the window or collapsed into the overflow group, the target side
still highlights and the caption still names the source by display name; the path
degrades gracefully rather than disappearing.

## Non-goals

- No storage/schema change and no migration.
- No change to serve ordering, curation, or the canonical boundary.
- No new automatic feedback behavior — this is presentation only.

## Testing

- `agent_activity` emits a trace when a handled feedback event's produced decision
  is later served to a different actor.
- No trace is emitted when the same actor serves a decision their own feedback
  produced (no self-traces).
- Decisions served that did not originate from feedback produce no trace.
- Traces de-duplicate on `(from, to, decision_id)`.
