# Design: curation & feedback UX improvements

- **Date:** 2026-06-09
- **Status:** approved
- **Surface:** the local curation web UI (`metatron ui`) — `metatron/webui/`.

## Goal

Tighten five rough edges in the curation and agent-impact views so a human
curator can act on knowledge without bouncing between screens, can correct and
author decision text directly, and can invoke the advisory judge on demand. None
of these changes touch the core invariant: **nothing crosses the canonical
boundary without an explicit human action.**

The five items, smallest to largest:

1. **Refine button reflow** — the "Refine into candidate" button resizes when its
   label swaps to "Refining…", leaving the spinner and text visually unbalanced.
2. **Constellation side panel** — in the Agent Impact graph the side panel snaps
   back to the team aggregate the moment the pointer leaves an engineer, so it is
   hard to read a single engineer's detail.
3. **Judge controls** — the Curation queue shows the advisory judge's verdicts but
   gives no way to *run* the judge: neither over the whole queue nor on one
   candidate.
4. **Review a refined gap in place** — after refining a "what was missing" gap, the
   curator must navigate to the Curation screen to approve or reject the resulting
   candidate.
5. **Editable & human-authored decisions** — a curator cannot correct a decision's
   text, nor author one by hand.

## The line we hold

- Manually-authored decisions and refined gaps both enter as **candidates**. No new
  path writes straight to canonical. Approval stays a separate, explicit human act.
- Editing a decision's *content* (pattern / scope / rationale / confidence) never
  changes its `status` or `triage`, so it cannot promote, demote, or un-reject.
  Editing is allowed for `candidate` and `canonical` decisions; `rejected` stays
  read-only.
- The per-candidate and queue-level judge actions are **advisory only** — they set
  `triage` + `triage_reason` and never change `status`, exactly like the existing
  background judge.

## Items

### 1 — Refine button reflow (frontend, CSS only)

`.btn` has no minimum width, so swapping the label in `GapCard`
(`views_impact.jsx`) from "Refine into candidate" to "Refining…" reflows the
button and unbalances the spinner. Give that specific button a `min-width` and
center its contents so the label/spinner swap in place. No JS or behavior change.

### 2 — Constellation side panel holds the last engineer (frontend)

In `AgentImpactView` (`views_impact.jsx`):

- Remove the `onMouseLeave={() => setFocusIdx(-1)}` reset on the graph container so
  the side panel **holds** the last-hovered engineer instead of reverting.
- Add an "All agents" control in the `AgentDetailPanel` header (`agent_flow.jsx`)
  that sets `focusIdx = -1`, returning to the team-aggregate panel.
- Initial load stays aggregate (`focusIdx === -1`) until the first hover. Hover
  still previews; there is simply no auto-revert.

No backend change.

### 3 — Judge controls: queue-level and per-candidate

**Queue-level (existing backend, new UI wiring).** The background judge job is
already exposed at `POST /api/valuate/start` and `GET /api/valuate/status`
(`webui/server.py`, `webui/jobs.py`). Add `startValuate(repo)` /
`getValuateStatus(repo)` to `api.js` and a "Run the judge" button in the Curation
header (`views_knowledge.jsx`) that starts the job, polls status, shows progress
(`triaged / total`), and reloads the queue on completion so triage tags and
reasons refresh.

**Per-candidate (new backend + UI).** Add `POST /api/decisions/{id}/valuate`:

- `webui/api.py`: `valuate_one(store, judge_factory, decision_id)` — load the
  decision, run `DecisionJudge.evaluate([decision])`, persist the verdict with
  `store.set_triage(id, verdict, reason)`, return the updated decision. Mirror
  `refine_one`'s defensive shape: if no judge provider is configured or the call
  fails, return `{ "ok": False, "error": ... }` rather than a 500.
- `webui/server.py`: route `POST /api/decisions/{id}/valuate` (alongside the
  existing `approve` / `reject` action routes).
- `api.js`: `valuateDecision(id)`.
- UI: an "Ask the judge" button on each `CandidateCard` that shows a spinner, then
  updates that card's `TriageTag` and reason in place from the returned decision.

The judge factory is threaded into the handler the same way `refiner_factory`
already is.

### 4 — Review a refined gap in place (backend + frontend)

Make refinement return what it created so the curator can act without leaving the
Feedback view.

- **Backend:** `refine_feedback_event` already records produced decision ids via
  `event_store.mark_handled(event_id, produced_ids)`. Surface those ids on its
  result, and have `api.refine_one` include `decision_ids` in its response. (Shape
  becomes `{ ok, events_processed, decisions_created, decision_ids }`.)
- **Frontend:** in `GapCard` (`views_impact.jsx`), after a successful refine, fetch
  the produced decisions (`getDecision`) and render them inline in a compact
  candidate card with **Approve / Reject / Inspect**, reusing the existing
  `approveDecision` / `rejectDecision` endpoints and the `openDecision` drawer.
  After approve/reject, reflect the new status inline. The static "A candidate
  decision was distilled from this gap." text is replaced by this inline review.

A handled gap reloaded from scratch (no `decision_ids` in hand) still needs its
candidates: `feedback-events` already marks the event handled; the gap card
resolves the produced ids from the handled event so inline review survives a
reload. (If the event store does not expose produced ids on read, add a read path
for them; confirmed during implementation.)

### 5 — Editable & human-authored decisions (backend + frontend)

A single shared `DecisionEditor` component powers both editing and authoring.

**Storage** (`storage/base.py`, `storage/sqlite.py`):

- `update_fields(decision_id, *, pattern=None, scope=None, rationale=None,
  confidence=None) -> Decision` — update only the provided content fields, bump
  `updated_at`, leave `status` / `triage` / `origin` untouched. Allowed for
  `candidate` and `canonical`; reject editing a `rejected` decision.
- Decision creation uses the existing `add(decision)`.

**Model** (`models.py`): add `Origin.HUMAN = "human"` for hand-authored decisions.
Thread it through the origin labels/tags (`ui.jsx` `OriginLabel` / `OriginTag`) and
the origin filter options (`views_knowledge.jsx` `ORIGIN_OPTS`).

**API** (`webui/api.py` + `webui/server.py`):

- `POST /api/decisions/{id}/update` → `api.update_decision(store, id, body)` —
  validates fields, calls `update_fields`, returns the updated decision. Refuses if
  the decision is `rejected`.
- `POST /api/decisions` (create) → `api.create_decision(store, body)` — builds a
  `Decision(status=candidate, origin=human, triage=none, model="")` from
  pattern/scope/rationale/confidence + `repo`, calls `add`, returns it. Validates
  that required text fields are present.
- `api.js`: `updateDecision(id, fields)`, `createDecision(repo, fields)`.

**UI** (`views_knowledge.jsx`, plus the decision drawer in `app.jsx` / `ui.jsx`):

- `DecisionEditor` — controlled fields for pattern (textarea), scope (input),
  rationale (textarea), confidence (select). Save / Cancel. Used in two modes:
  - **Edit:** a pencil control on `CandidateCard` (and the decision drawer) opens the
    editor populated from the decision; Save calls `updateDecision`.
  - **Add:** a "+ Add decision" button in the Curation header opens the editor empty;
    Save calls `createDecision` and the new candidate appears in the queue.
- Manual adds start as `candidate`; a later peer-review path is out of scope here.

## Out of scope

- Any peer-review / multi-curator approval flow for manual adds (noted as future).
- Editing `rejected` decisions.
- Changing `status` from the editor (promotion stays the Approve action).
- Postgres, auth, or any non-local surface (unchanged from project scope).

## PR decomposition

Per the repo's "small, reviewable PRs, each with tests" rule, four PRs, each
independently mergeable:

- **PR-A — frontend polish:** items 1 + 2. Pure frontend; `node:test` coverage for
  any extracted logic (e.g. focus-hold helper if introduced).
- **PR-B — judge controls:** item 3. Backend `valuate_one` + route; `api.js`
  wiring; UI buttons. pytest for `valuate_one` (configured / unconfigured / error
  paths); `node:test` for status-polling logic if extracted.
- **PR-C — inline gap review:** item 4. Backend `decision_ids` surfacing; frontend
  inline candidate review. pytest for the refine result shape; `node:test` for the
  gap-card state transitions if extracted.
- **PR-D — editable & authored decisions:** item 5. `update_fields`, `Origin.HUMAN`,
  create/update endpoints, shared `DecisionEditor`. pytest for `update_fields`
  (field-by-field, status guard) and the create/update endpoints; `node:test` for
  editor field validation if extracted.

## Testing

- **Backend (pytest):** new store methods and endpoints get unit tests beside the
  existing `tests/test_*` suite. Judge and refiner paths are tested with stub
  factories (the codebase already injects `*_factory` callables, so no live LLM is
  needed), covering the unconfigured and error branches.
- **Frontend (`node --test`):** the app has no build step and tests pure logic only.
  Where an item adds non-trivial logic (status polling, focus-hold, editor
  validation, gap-card state), that logic is extracted into a plain module with a
  `*.test.js` beside it, matching the existing `activity_signature` / `agent_trace`
  pattern. Presentational JSX is verified manually against the running UI.

## Risks & mitigations

- **Judge cost / latency on demand.** Per-candidate and queue runs call an LLM.
  Both reuse the existing job/factory plumbing (lazy provider construction, clean
  `ok: false` when unconfigured) so a missing key degrades gracefully rather than
  erroring.
- **Edit racing the background judge.** Editing content does not touch `triage`, so
  a stale verdict can linger after an edit; the curator can re-run "Ask the judge"
  on that card. Acceptable and explicit.
- **Origin enum growth.** Adding `Origin.HUMAN` touches every place origins are
  rendered or filtered; the design lists those call sites so none is missed.
