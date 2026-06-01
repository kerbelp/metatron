# Design: agent feedback loop (capture → candidate, human-gated)

- **Date:** 2026-06-01
- **Status:** proposed (awaiting approval)
- **Maps to:** `docs/future-features.md` item **B** (helpfulness feedback). Item **C**
  (automatic self-improvement) stays deferred — see Non-goals.

## Goal

Let a coding agent, after using Metatron on a task, tell us **how helpful the
served priors were** and — most valuably — **what convention was missing**. Route
that signal into the existing curation queue so a human can periodically ("fine-tune
once in a while") turn real gaps into canonical priors.

Motivated by real feedback (2026-06-01): an agent's most decision-relevant
knowledge — "the credit path must mirror the `order_created` webhook publish chain;
the ledger atomic-consume/refund pattern" — **was never extracted** (see
`memory/extraction-recall-gap`). That comment is higher-signal raw material than our
structural extractor produces. We want to capture it.

We also want to **measure improvement over time**: every served response and every
piece of feedback is stamped with the **build revision** that produced it, so we can
correlate quality (e.g. helpful-rate) with specific builds as we tune the extractor
and ranker.

## Non-goals (the line we hold)

The core principle stands: **nothing self-promotes; a human curates everything into
the canonical set.**

- **No auto-canonicalization.** Feedback never creates a *canonical* prior. "What was
  missing" becomes a **candidate** in the normal queue.
- **Ratings are advisory.** Helpful/unhelpful counts are shown to the curator (like
  the triage verdicts); they do **not** auto-adjust confidence, auto-demote, or
  auto-delete anything.
- **Feature C stays deferred.** Closing the loop to automatic mutation requires the
  offline eval harness (item A) first — you cannot safely auto-optimize a metric you
  cannot yet trust.

## The loop

```
serve priors → agent works → agent calls submit_feedback
   ├─ ratings (which served priors helped / were noise)  → advisory FEEDBACK event
   └─ what_was_missing (free text)                        → CANDIDATE prior (agent_feedback)
                                                              → human curates → canonical
```

## MCP surface

### 1. New tool: `submit_feedback`

```
submit_feedback(
    query_id: str | "",          # the token Metatron returned with the priors
    helpful: list[int] = [],     # 1-based indices of served priors that helped
    unhelpful: list[int] = [],   # 1-based indices that were noise
    what_was_missing: str = "",  # the convention Metatron should have had
    missing_scope: str = "",     # optional scope hint for the candidate
) -> str                         # human-readable confirmation
```

- `helpful`/`unhelpful` are **small integer indices**, not UUIDs. We learned from the
  triage bug (`memory/...`) that models mangle UUIDs; indices + a single `query_id`
  token are robust. Indices are resolved to real prior ids **locally**, against the
  stored QUERY event; out-of-range indices are ignored, not fatal.
- `what_was_missing` (if present) creates a candidate via the existing
  `submit_candidate_learning` path with `origin = agent_feedback`, scope =
  `missing_scope` or the query's area, `confidence = high` (flags it for prompt
  curation — high confidence ≠ canonical; it is still a candidate).
- `query_id` is **optional**: a pure gap report with an explicit `missing_scope` is
  valid even with no ratings.

### 2. Expose a query token + indices in served output

`get_priors_for_context` today returns text with no handles. We add:

```
metatron:query 7f3c… · rev 7ed9eea (reference the query id in submit_feedback)
[1] [high] <pattern>  scope: …  why: …
[2] [med]  <pattern>  …
```

The `query_id` is the id of the QUERY event we already record (it stores
`prior_ids` in rank order). `submit_feedback` looks the event up and maps
`helpful=[1]` → `prior_ids[0]`.

**Build revision on every response.** All MCP responses (`get_priors_for_context`,
`submit_feedback`, `submit_candidate_learning`) include `rev <hash>` from
`metatron.version`. This makes the serving build visible to the agent/curator, and —
combined with the event stamping below — lets us track quality across builds.

## Data model (additive, migration-safe)

- `Origin.AGENT_FEEDBACK = "agent_feedback"` — provenance for gap-born candidates.
- `EventKind.FEEDBACK = "feedback"`.
- `Event` gains nullable fields, persisted via `_ensure_column` (same pattern as the
  repo/model/triage migrations):
  - `version: str` — **the build revision that produced the event**, stamped on
    *every* event (query, submit, feedback). Defaulted from a process-cached
    `metatron.version.version_string()` (the build is constant for a process, so the
    git lookup is cached — no subprocess per event).
  - `query_ref: str` — the QUERY event this responds to.
  - `helpful_prior_ids: list[str]`, `unhelpful_prior_ids: list[str]` (JSON).
  - `missing: str` — the gap text (also copied onto the created candidate's rationale).
- `EventStore` gains `get(event_id)` so `submit_feedback` can resolve indices.

No new tables; feedback is a usage event in the existing `events` table.

## Curation surface (where the human acts)

- **Gap candidates:** appear in the existing Candidates queue (CLI `candidates list`,
  UI Candidates tab) with an `agent_feedback` origin badge, `confidence=high` so they
  sort to the top and are caught by `triage`. Curated exactly like any candidate.
- **Advisory ratings:** the Observability tab gains a per-canonical-prior tally —
  "served N×, helpful H, noise X" — so during a curation pass the human can spot a
  consistently-noisy prior to **review** (not auto-demote) or a consistently-helpful
  one to keep. Mirrors the triage "advisory, human decides" model.
- **Quality over time:** because every event carries `version`, the helpful-rate can
  be grouped by build — the basis for "did this change actually improve serving?"
  (Phase-4 surfaces the per-prior tally; a build-over-build view can follow once
  there is enough feedback to be meaningful.)

## Agent guidance

Update the onboarding so agents actually call it (capture is worthless if unused):

- CLAUDE.md block + `metatron_reminder.txt` (the UserPromptSubmit hook): "After a
  task where you consulted Metatron, call `submit_feedback` — reference the query
  token, mark which priors helped, and **state any convention Metatron should have
  known but didn't**."
- `metatron_setup.sh` writes this guidance (additive/idempotent, as today).

## Privacy

Unlike extraction (which sends only structural signals — never source — to the LLM),
`what_was_missing` and ratings **will** contain code-derived prose. This is fine:
it is stored in the **local** SQLite DB and never sent anywhere. Feedback text is
**not** fed to any LLM call unless/until a later, deliberate decision (e.g. feeding
gap candidates to the triage judge) — and that would be its own change.

## Testing strategy (TDD throughout)

- Index→prior-id resolution: correct mapping, out-of-range ignored, missing query_id
  tolerated.
- `submit_feedback` with `what_was_missing` creates exactly one `candidate`
  (`agent_feedback`, never canonical); status stays `candidate`.
- FEEDBACK event recorded with the right helpful/unhelpful ids.
- Served output includes a stable query token and 1-based indices.
- Advisory tally aggregates feedback events per prior; asserts no status/confidence
  mutation occurs.
- Every recorded event carries a non-empty `version`; the served response text
  includes `rev <hash>`; the revision lookup is cached (one git call per process).

## Phasing (small, reviewable PRs)

1. **Model + storage:** `Origin.AGENT_FEEDBACK`, `EventKind.FEEDBACK`, `Event` fields,
   sqlite `_ensure_column` migrations, `EventStore.get`.
2. **Service:** `submit_feedback` (index mapping, candidate creation) + query-token /
   indices in `get_priors_for_context` output.
3. **MCP tool:** register `submit_feedback` in the server; record the FEEDBACK event.
4. **Curation surface:** origin badge on candidates + advisory per-prior tally in the
   Observability tab.
5. **Guidance:** CLAUDE.md block + reminder + `metatron_setup.sh`.

## Open questions

- `confidence=high` vs a dedicated "priority" flag for gap candidates — `high` reuses
  existing sorting/triage with no schema change; revisit if it muddies real confidence.
- Should repeated identical gap reports dedupe/upvote a single candidate? Deferred;
  v1 creates one candidate per report and the human merges during curation.
