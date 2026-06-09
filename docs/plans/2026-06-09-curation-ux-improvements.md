# Curation & Feedback UX Improvements — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten five curation/agent-impact UX rough edges — refine-button reflow, a sticky engineer panel, on-demand judge controls, inline review of refined gaps, and editable + human-authored decisions.

**Architecture:** Plain-React frontend (`metatron/webui/app/*.jsx`, no build step, CDN React; pure-logic tests via `node --test`) over a stdlib-HTTP backend (`webui/server.py` routing to `webui/api.py` functions) on top of a swappable `DecisionStore` (SQLite). Each PR is independently mergeable and includes tests. The canonical-boundary invariant holds throughout: nothing self-promotes, edits never touch `status`/`triage`, manual adds enter as candidates.

**Tech Stack:** Python 3.12 (pytest, `uv run`), stdlib `http.server`, Pydantic models, SQLite; plain React 18 via CDN, `node:test`.

**Spec:** `docs/designs/2026-06-09-curation-ux-improvements.md`

**Conventions (read before any commit):**
- Public repo — every commit message is a neutral, third-person technical note. Never reference the chat, "the user", screenshots, or this session.
- Run backend tests with `uv run pytest <path> -v`; frontend tests with `npm test` (or `node --test 'metatron/webui/app/**/*.test.js'`).
- No direct commits to `main`; this work lives on branch `feat/curation-ux`.
- Frontend has no build step — JSX is verified by loading the running UI; only extracted pure logic gets `node:test` coverage.

---

## PR-A — Frontend polish (items 1 & 2)

Pure frontend. Item 1 is CSS-only; item 2 changes hover-reset behavior and adds an "All agents" control. No extractable logic warrants a new `node:test` here — verify in the running UI.

### Task A1: Stop the refine button reflowing (item 1)

**Files:**
- Modify: `metatron/webui/app/styles.css` (the `.btn` rules, ~line 242–255)
- Modify: `metatron/webui/app/views_impact.jsx:325-327` (the refine button)

- [ ] **Step 1: Add a reusable fixed-width modifier to the button CSS**

In `styles.css`, after the `.btn:disabled` rule (~line 254), add:

```css
.btn.fixed { min-width: 188px; justify-content: center; }
```

(`.btn` is already `display:inline-flex` with `gap`; `justify-content:center` keeps the label/spinner centered when the text length changes.)

- [ ] **Step 2: Apply it to the refine button**

In `views_impact.jsx`, change the button's class from `"btn primary"` to `"btn primary fixed"`:

```jsx
<button className="btn primary fixed" disabled={e.handled || refining} onClick={onRefine}>
  {refining ? <><Spinner size={15} /> Refining…</> : e.handled ? <><Icon name="check" size={15} /> Refined</> : <><Icon name="loop" size={15} /> Refine into candidate</>}
</button>
```

- [ ] **Step 3: Verify in the running UI**

Run the UI (`uv run metatron ui` against a repo with feedback gaps), click "Refine into candidate", and confirm the button keeps its width and the spinner/label stay centered through the `Refine into candidate → Refining… → Refined` transitions.

- [ ] **Step 4: Commit**

```bash
git add metatron/webui/app/styles.css metatron/webui/app/views_impact.jsx
git commit -m "fix(webui): keep the refine button from reflowing while it runs"
```

### Task A2: Hold the constellation side panel; add an "All agents" reset (item 2)

**Files:**
- Modify: `metatron/webui/app/views_impact.jsx:112` (remove the mouse-leave reset) and `:120-124` (pass `onClearFocus`)
- Modify: `metatron/webui/app/agent_flow.jsx` (`AgentDetailPanel`, ~line 236+) to render the "All agents" control

- [ ] **Step 1: Remove the auto-revert on mouse-leave**

In `views_impact.jsx`, the constellation container currently resets focus when the pointer leaves:

```jsx
<div onMouseLeave={() => setFocusIdx(-1)} style={{ position: "relative", borderRight: ...
```

Remove the `onMouseLeave={() => setFocusIdx(-1)}` handler so the panel holds the last-hovered engineer:

```jsx
<div style={{ position: "relative", borderRight: ...
```

Leave the existing `useEffect(() => { setFocusIdx(-1); }, [repo, windowMins]);` (line 56) untouched — initial/aggregate state still resets on repo/window change.

- [ ] **Step 2: Pass an `onClearFocus` callback to the detail panel**

In `views_impact.jsx`, where `AgentDetailPanel` is rendered (~line 122), add the prop:

```jsx
{agNodes[fIdx]
  ? <AgentDetailPanel node={agNodes[fIdx]} onClearFocus={() => setFocusIdx(-1)} onDrill={(a, focus) => openPanel && openPanel({ type: "agent", agent: a, focus })} />
  : <AgentAggregatePanel data={act.data} />}
```

- [ ] **Step 3: Render the "All agents" control in `AgentDetailPanel`**

In `agent_flow.jsx`, find the `AgentDetailPanel` function signature and add `onClearFocus` to its props. In its header row (where the agent name/title renders), add a small back control, styled like the existing `chip` buttons:

```jsx
{onClearFocus && (
  <button className="chip" onClick={onClearFocus} title="Back to the team view"
    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
    <Icon name="arrow" size={13} style={{ transform: "rotate(180deg)" }} /> All agents
  </button>
)}
```

Place it so it reads as a header affordance (e.g. top-right of the panel header). Match the surrounding spacing; do not restructure the panel.

- [ ] **Step 4: Verify in the running UI**

Hover an engineer, move the pointer off the node, and confirm the panel **stays** on that engineer. Click "All agents" and confirm it returns to the aggregate (`AgentAggregatePanel`). Switch the time window and confirm it resets to aggregate.

- [ ] **Step 5: Commit**

```bash
git add metatron/webui/app/views_impact.jsx metatron/webui/app/agent_flow.jsx
git commit -m "feat(webui): hold the agent impact side panel on the last engineer, with an all-agents reset"
```

---

## PR-B — Judge controls (item 3)

Adds a per-candidate `valuate_one` endpoint and wires both the existing queue-level valuate job and the new per-candidate action into the Curation UI. Backend gets TDD coverage; frontend JSX is verified live.

### Task B1: `valuate_one` API function

**Files:**
- Modify: `metatron/webui/api.py` (add `valuate_one`, near `refine_one` ~line 513)
- Test: `tests/test_web_api.py`

The judge is built the way `TriageJob` builds it: from a provider factory via `DecisionJudge(provider)` (`webui/jobs.py:113-116`). `DecisionJudge.evaluate(candidates)` takes a list and returns per-decision verdicts; mirror how `TriageJob` consumes it (read `extraction/triage.py` `DecisionJudge.evaluate` for the exact return shape and adapt — it yields `(decision_id, verdict, reason)` per item or an indexed map; follow the job's usage).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_api.py` (import `valuate_one` and `TriageVerdict`):

```python
from metatron.models import TriageVerdict
from metatron.webui.api import valuate_one


class _StubJudge:
    """Stands in for DecisionJudge: returns a fixed verdict for each candidate."""
    def __init__(self, verdict=TriageVerdict.APPROVE, reason="looks canonical"):
        self.verdict, self.reason = verdict, reason
    def evaluate(self, candidates, **kw):
        # match DecisionJudge.evaluate's contract (see extraction/triage.py)
        return [(c.id, self.verdict, self.reason) for c in candidates]


def test_valuate_one_sets_triage(store):
    [d] = _add(store, 1)
    out = valuate_one(store, lambda: object(), d.id, judge_factory=lambda _p: _StubJudge())
    assert out["ok"] is True
    assert out["triage"] == "approve"
    assert store.get(d.id).triage is TriageVerdict.APPROVE
    assert store.get(d.id).triage_reason == "looks canonical"


def test_valuate_one_unconfigured_provider_is_clean_error(store):
    [d] = _add(store, 1)
    out = valuate_one(store, None, d.id)
    assert out["ok"] is False and "provider" in out["error"].lower()


def test_valuate_one_unknown_id(store):
    out = valuate_one(store, lambda: object(), "nope", judge_factory=lambda _p: _StubJudge())
    assert out["ok"] is False and "not found" in out["error"].lower()
```

- [ ] **Step 2: Run the tests — expect failure**

Run: `uv run pytest tests/test_web_api.py -k valuate_one -v`
Expected: FAIL (`ImportError: cannot import name 'valuate_one'`).

- [ ] **Step 3: Implement `valuate_one`**

In `webui/api.py`, near `refine_one`:

```python
def valuate_one(store, provider_factory, decision_id, *, judge_factory=None):
    """Run the advisory judge on a single decision (the per-candidate "Ask the judge").

    Advisory only: sets triage + reason, never status. ``provider_factory`` lazily
    builds the LLM provider (so the API key is only touched on demand); ``judge_factory``
    wraps it as a DecisionJudge (overridable in tests). Returns ``ok: False`` with a
    message — never a 500 — when unconfigured, the id is unknown, or the judge errors.
    """
    if provider_factory is None:
        return {"ok": False, "error": "Valuation needs an LLM provider. "
                "Set ANTHROPIC_API_KEY and restart `metatron ui`."}
    decision = store.get(decision_id)
    if decision is None:
        return {"ok": False, "error": f"No decision with id {decision_id!r} (not found)."}
    if judge_factory is None:
        from metatron.webui.jobs import _default_judge_factory as judge_factory
    try:
        judge = judge_factory(provider_factory())
        results = judge.evaluate([decision])
    except Exception as exc:  # provider/network/parse — message, not a crash
        return {"ok": False, "error": str(exc)}
    # results map 1:1 to the single candidate we passed
    _id, verdict, reason = list(results)[0]
    updated = store.set_triage(decision.id, verdict, reason)
    return {"ok": True, "id": updated.id, "triage": updated.triage.value,
            "triage_reason": updated.triage_reason}
```

Adjust the `results` unpacking to match `DecisionJudge.evaluate`'s real return shape (confirm against `extraction/triage.py`; if it returns an index→verdict map like `TriageJob` consumes, adapt accordingly and keep the test's `_StubJudge` in sync).

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run pytest tests/test_web_api.py -k valuate_one -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add metatron/webui/api.py tests/test_web_api.py
git commit -m "feat(webui): add valuate_one to run the advisory judge on a single decision"
```

### Task B2: Route the per-candidate valuate endpoint

**Files:**
- Modify: `metatron/webui/server.py:220-226` (the `/api/decisions/<id>/<action>` block)

- [ ] **Step 1: Add the route**

In `server.py`'s `do_POST`, inside the `len(segments) == 4 and segments[:2] == ["api", "decisions"]` block, add a `valuate` action alongside `approve`/`reject`:

```python
if action == "valuate":
    return self._send_json(
        api.valuate_one(store, ingest_provider_factory, decision_id)
    )
```

(`ingest_provider_factory` is already in the handler closure — see `_build_handler(store, event_store, refiner_factory, ingest_provider_factory)`.)

- [ ] **Step 2: Verify the route resolves**

Start the UI and `curl -X POST localhost:<port>/api/decisions/<a-real-candidate-id>/valuate`. With no API key set, expect a clean JSON `{"ok": false, "error": "Valuation needs an LLM provider…"}` (HTTP 200), not a 404 or stack trace.

- [ ] **Step 3: Commit**

```bash
git add metatron/webui/server.py
git commit -m "feat(webui): route POST /api/decisions/<id>/valuate to the single-decision judge"
```

### Task B3: API-client methods for the judge

**Files:**
- Modify: `metatron/webui/app/api.js` (add `startValuate`, `getValuateStatus`, `valuateDecision`)

- [ ] **Step 1: Add the methods**

In `api.js`'s `API` object:

```javascript
startValuate(repo) {
  return P("/api/valuate/start", { repo });
},
getValuateStatus(repo) {
  return J("/api/valuate/status?" + qs({ repo }));
},
valuateDecision(id) {
  return P(`/api/decisions/${id}/valuate`);
},
```

(Confirm `/api/valuate/status` takes/needs `repo`; the GET handler is at `server.py:163` → `triage_job.status()`. If status is global, drop the `qs`.)

- [ ] **Step 2: Commit**

```bash
git add metatron/webui/app/api.js
git commit -m "feat(webui): add api-client methods for queue and per-decision valuation"
```

### Task B4: Queue-level "Run the judge" button

**Files:**
- Modify: `metatron/webui/app/views_knowledge.jsx` (`CurationView`, ~line 171–238)

- [ ] **Step 1: Add valuate state + handler to `CurationView`**

Inside `CurationView`, add state and a start/poll handler that reuses the existing `usePolledApi`/polling idiom already used elsewhere (see `views_impact.jsx` for `usePolledApi`). Minimal version:

```jsx
const [valuating, setValuating] = useState(false);
const runJudge = async () => {
  setValuating(true);
  await MetatronAPI.startValuate(repo);
  // poll until the job reports done, then refresh the queue
  const tick = setInterval(async () => {
    const s = await MetatronAPI.getValuateStatus(repo);
    if (s.state !== "running") {
      clearInterval(tick);
      setValuating(false);
      res.reload(); refresh && refresh();
    }
  }, 1200);
};
```

(Match the field names the status endpoint actually returns — confirm `state`/`triaged`/`total` against `TriageJob.status()` in `jobs.py`.)

- [ ] **Step 2: Add the header button**

In the `SectionTitle`'s `right` slot (next to "Approve all … recommended"), add:

```jsx
<button className="btn fixed" disabled={valuating} onClick={runJudge}>
  {valuating ? <><Spinner size={15} /> Running the judge…</> : <><Icon name="spark" size={15} /> Run the judge</>}
</button>
```

- [ ] **Step 3: Verify in the running UI**

With a configured `ANTHROPIC_API_KEY` and untriaged candidates present, click "Run the judge", confirm progress shows, and the triage tags/counts refresh when it finishes. Without a key, confirm the button surfaces the clean error (toast) rather than hanging.

- [ ] **Step 4: Commit**

```bash
git add metatron/webui/app/views_knowledge.jsx
git commit -m "feat(webui): add a run-the-judge control to the curation queue"
```

### Task B5: Per-candidate "Ask the judge" button

**Files:**
- Modify: `metatron/webui/app/views_knowledge.jsx` (`CandidateCard`, ~line 245–277, and its call site ~line 235)

- [ ] **Step 1: Thread an `onValuate` handler from `CurationView`**

In `CurationView`'s card map, pass a per-card valuate handler that calls the endpoint and reloads on success:

```jsx
<CandidateCard ... onValuate={async () => { await MetatronAPI.valuateDecision(p.id); res.reload(); }} />
```

- [ ] **Step 2: Add the button + busy state to `CandidateCard`**

Add `onValuate` to `CandidateCard`'s props and a local `const [asking, setAsking] = useState(false);`. In the right-hand button column (next to Approve/Reject/Inspect), add:

```jsx
<button className="btn" disabled={asking} style={{ fontSize: 12 }}
  onClick={async () => { setAsking(true); try { await onValuate(); } finally { setAsking(false); } }}>
  {asking ? <><Spinner size={13} /> Asking…</> : <><Icon name="spark" size={13} /> Ask the judge</>}
</button>
```

The card already renders `TriageTag`/`triage_reason` from `p`, so a successful `res.reload()` updates the verdict in place.

- [ ] **Step 3: Verify in the running UI**

On a candidate, click "Ask the judge"; confirm a spinner, then its triage tag + reason update. Confirm the unconfigured-provider case shows a clean error.

- [ ] **Step 4: Commit**

```bash
git add metatron/webui/app/views_knowledge.jsx
git commit -m "feat(webui): add a per-candidate ask-the-judge control"
```

---

## PR-C — Inline review of a refined gap (item 4)

`refine_one` returns the created candidate ids; `GapCard` renders them inline with Approve/Reject/Inspect. On reload, the produced candidates resolve from the already-handled feedback event (read path exists — `feedback_events` already surfaces them).

### Task C1: Surface produced decision ids from refinement

**Files:**
- Modify: `metatron/pipeline.py` (`RefineResult` ~line 43, `refine_feedback_event` ~line 93)
- Modify: `metatron/webui/api.py` (`refine_one` ~line 536)
- Test: `tests/test_feedback_refiner.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_feedback_refiner.py`, add a test asserting the result carries the produced ids (use the existing `StaticProvider` + store fixtures in that file; mirror an existing `refine_feedback_event` test for setup):

```python
def test_refine_feedback_event_returns_produced_ids(...):
    # ... arrange an unhandled feedback event + a StaticProvider that yields 1 candidate
    result = refine_feedback_event(store, event_store, refiner, event.id)
    assert result.decisions_created == 1
    assert len(result.decision_ids) == 1
    assert store.get(result.decision_ids[0]) is not None
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_feedback_refiner.py -k returns_produced_ids -v`
Expected: FAIL (`RefineResult` has no `decision_ids`).

- [ ] **Step 3: Add `decision_ids` to `RefineResult` and thread it through**

In `pipeline.py`:

```python
class RefineResult(BaseModel):
    events_processed: int
    decisions_created: int
    decision_ids: list[str] = []
```

In `refine_feedback_event` (the single-event path), `_refine_one` already returns `produced` (the list of ids). Capture and pass it:

```python
produced = _refine_one(store, event_store, refiner, event)
return RefineResult(events_processed=1, decisions_created=len(produced), decision_ids=produced)
```

(Leave the batch `refine_feedback` path's `decision_ids` defaulting to `[]` unless a test needs it — YAGNI.)

In `webui/api.py` `refine_one`, add the ids to the response dict:

```python
return {
    "ok": True,
    "events_processed": result.events_processed,
    "decisions_created": result.decisions_created,
    "decision_ids": result.decision_ids,
}
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_feedback_refiner.py -k returns_produced_ids -v`
Expected: PASS. Then run the full file to confirm no regression: `uv run pytest tests/test_feedback_refiner.py -v`.

- [ ] **Step 5: Commit**

```bash
git add metatron/pipeline.py metatron/webui/api.py tests/test_feedback_refiner.py
git commit -m "feat: return produced candidate ids from single-event refinement"
```

### Task C2: Inline candidate review in `GapCard`

**Files:**
- Modify: `metatron/webui/app/views_impact.jsx` (`FeedbackLoopView` ~line 229–279 and `GapCard` ~line 287–331)

The handled-event read path: `feedback-events` items already expose the produced candidate ids (confirm the field name on `e` — e.g. `e.decision_ids` — by inspecting an event in the running `/api/feedback-events` response; the backend records them via `mark_handled`).

- [ ] **Step 1: Capture produced ids on refine**

In `FeedbackLoopView.doRefine`, keep the returned ids so the just-refined card can show its candidate without waiting for a reload:

```jsx
const doRefine = async (e) => {
  setRefining(e.id);
  const res = await MetatronAPI.refineFeedback(e.id);
  setRefining(null);
  toast("Gap refined into a new candidate decision", { icon: "loop" });
  ev.reload(); refresh && refresh();
  return res && res.decision_ids;  // GapCard uses these immediately
};
```

Adjust the `onRefine` prop plumbing so `GapCard` receives the produced ids (either via the return value or a small piece of state keyed by `e.id`).

- [ ] **Step 2: Render inline candidates in the handled branch of `GapCard`**

Replace the static handled text:

```jsx
<span className="mono dim" style={{ fontSize: 11 }}>{e.handled ? "A candidate decision was distilled from this gap." : "Distill this gap into a new candidate decision for human review."}</span>
```

When `e.handled` (or freshly refined), resolve the produced ids (`e.decision_ids` on reload, or the ids returned from `doRefine`) and render a compact inline review for each — load each with `MetatronAPI.getDecision(id)` and show pattern + **Approve / Reject / Inspect**:

```jsx
function InlineCandidate({ id, onOpenDecision, onChanged }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { MetatronAPI.getDecision(id).then(setD); }, [id]);
  if (!d || !d.id) return null;
  const act = (fn) => async () => { setBusy(true); await fn(d.id); const fresh = await MetatronAPI.getDecision(id); setD(fresh); setBusy(false); onChanged && onChanged(); };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 13px", borderRadius: 10, border: "1px solid var(--line)", background: "rgba(8,18,16,.4)" }}>
      <StatusBadge status={d.status} />
      <span style={{ flex: 1, fontSize: 13, color: "var(--text)" }}>{d.pattern}</span>
      {d.status === "candidate" ? <>
        <button className="btn primary" disabled={busy} onClick={act(MetatronAPI.approveDecision)}><Icon name="check" size={14} />Approve</button>
        <button className="btn danger" disabled={busy} onClick={act(MetatronAPI.rejectDecision)}><Icon name="x" size={14} />Reject</button>
      </> : null}
      <button className="btn" style={{ fontSize: 12 }} onClick={() => onOpenDecision(d.id)}>Inspect</button>
    </div>
  );
}
```

Render one `InlineCandidate` per produced id in place of the old text, keeping the "Refine into candidate" button for the unhandled state. `StatusBadge` and `getDecision`/`approveDecision`/`rejectDecision` already exist.

- [ ] **Step 3: Verify in the running UI**

Refine an open gap; confirm the distilled candidate appears inline with Approve/Reject/Inspect, that approving it flips the inline badge to canonical (and removes it from the Curation queue), and that reloading the Feedback view still shows the inline candidate for already-handled gaps.

- [ ] **Step 4: Commit**

```bash
git add metatron/webui/app/views_impact.jsx
git commit -m "feat(webui): review a refined gap's candidate inline in the feedback view"
```

---

## PR-D — Editable & human-authored decisions (item 5)

Adds a content-only `update_fields` store method, an `Origin.HUMAN` provenance, create/update endpoints, and a shared `DecisionEditor` used for both editing (candidate + canonical) and manual authoring (creates a candidate).

### Task D1: `Origin.HUMAN`

**Files:**
- Modify: `metatron/models.py:32-35` (the `Origin` enum)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_models.py`, assert the new origin exists and round-trips:

```python
def test_origin_human_exists():
    from metatron.models import Origin
    assert Origin("human") is Origin.HUMAN
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_models.py -k origin_human -v` → FAIL (`ValueError: 'human' is not a valid Origin`).

- [ ] **Step 3: Add the enum member**

In `models.py`:

```python
class Origin(str, enum.Enum):
    BOOTSTRAP = "bootstrap"
    AGENT_SUBMITTED = "agent_submitted"
    AGENT_FEEDBACK = "agent_feedback"  # born from a "what was missing" feedback report
    HUMAN = "human"  # authored directly by a human curator in the UI
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_models.py -k origin_human -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add metatron/models.py tests/test_models.py
git commit -m "feat(models): add a human origin for curator-authored decisions"
```

### Task D2: `update_fields` store method

**Files:**
- Modify: `metatron/storage/base.py` (add abstract `update_fields`, ~after `set_status` line 73)
- Modify: `metatron/storage/sqlite.py` (implement, near `set_status` line 198)
- Test: `tests/test_catalog_stores.py` (or wherever store contract tests live — confirm)

- [ ] **Step 1: Write the failing tests**

Add to the store test suite (mirror its existing fixture/setup):

```python
def test_update_fields_edits_content_only(store):
    d = store.add(Decision(repo="r", pattern="old", scope="app", rationale="why",
                           origin=Origin.HUMAN, status=Status.CANONICAL))
    out = store.update_fields(d.id, pattern="new", rationale="better")
    assert out.pattern == "new" and out.rationale == "better"
    assert out.scope == "app"                 # untouched
    assert out.status is Status.CANONICAL     # never changed by an edit
    assert out.updated_at >= d.updated_at

def test_update_fields_rejects_unknown_id(store):
    with pytest.raises(KeyError):
        store.update_fields("nope", pattern="x")
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest <store-test-file> -k update_fields -v` → FAIL (`AttributeError`/abstract).

- [ ] **Step 3: Declare the abstract method**

In `storage/base.py`, after `set_status`:

```python
@abstractmethod
def update_fields(
    self, decision_id: str, *, pattern: str | None = None, scope: str | None = None,
    rationale: str | None = None, confidence: "Confidence | None" = None,
) -> Decision:
    """Update a decision's *content* fields (only the ones provided), bump
    ``updated_at``, and return it. Never touches ``status``/``triage``/``origin``.
    Raises ``KeyError`` if no decision has this id.
    """
```

Add `Confidence` to the `from metatron.models import ...` line in `base.py`.

- [ ] **Step 4: Implement in SQLite**

In `storage/sqlite.py`, near `set_status` (mirror its `model_copy` + targeted `UPDATE`):

```python
def update_fields(self, decision_id, *, pattern=None, scope=None, rationale=None, confidence=None):
    decision = self.get(decision_id)
    if decision is None:
        raise KeyError(decision_id)
    changes = {k: v for k, v in
               {"pattern": pattern, "scope": scope, "rationale": rationale, "confidence": confidence}.items()
               if v is not None}
    now = datetime.now(timezone.utc)
    updated = decision.model_copy(update={**changes, "updated_at": now})
    self._conn.execute(
        "UPDATE decisions SET pattern = ?, scope = ?, rationale = ?, confidence = ?, updated_at = ? WHERE id = ?",
        (updated.pattern, updated.scope, updated.rationale, updated.confidence.value,
         updated.updated_at.isoformat(), decision_id),
    )
    self._conn.commit()
    return updated
```

(If there are other `DecisionStore` implementations beyond SQLite, implement there too — check `storage/` for any in-memory store used in tests.)

- [ ] **Step 5: Run — expect pass**

Run: `uv run pytest <store-test-file> -k update_fields -v` → PASS. Then the whole store suite to confirm the new abstract method didn't break another implementation.

- [ ] **Step 6: Commit**

```bash
git add metatron/storage/base.py metatron/storage/sqlite.py tests/<store-test-file>
git commit -m "feat(storage): add update_fields to edit a decision's content"
```

### Task D3: create + update API functions and routes

**Files:**
- Modify: `metatron/webui/api.py` (add `create_decision`, `update_decision`)
- Modify: `metatron/webui/server.py` (`POST /api/decisions`, `POST /api/decisions/<id>/update`)
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Write the failing tests**

```python
from metatron.webui.api import create_decision, update_decision

def test_create_decision_makes_a_human_candidate(store):
    out = create_decision(store, {"repo": "r", "pattern": "p", "scope": "app", "rationale": "why"})
    assert out["ok"] is True
    d = store.get(out["id"])
    assert d.status is Status.CANDIDATE and d.origin is Origin.HUMAN

def test_create_decision_requires_pattern(store):
    out = create_decision(store, {"repo": "r", "scope": "app", "rationale": "why"})
    assert out["ok"] is False

def test_update_decision_edits_candidate(store):
    [d] = _add(store, 1)
    out = update_decision(store, d.id, {"pattern": "edited"})
    assert out["ok"] is True and store.get(d.id).pattern == "edited"

def test_update_decision_refuses_rejected(store):
    [d] = _add(store, 1, status=Status.REJECTED)
    out = update_decision(store, d.id, {"pattern": "x"})
    assert out["ok"] is False and "reject" in out["error"].lower()
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_web_api.py -k "create_decision or update_decision" -v` → FAIL (ImportError).

- [ ] **Step 3: Implement the functions**

In `webui/api.py`:

```python
def create_decision(store, body: dict) -> dict:
    """Create a human-authored candidate from the editor form. Candidate + human
    origin; approval stays a separate human action."""
    from metatron.models import Confidence, Decision, Origin, Status
    pattern = (body.get("pattern") or "").strip()
    scope = (body.get("scope") or "").strip()
    rationale = (body.get("rationale") or "").strip()
    repo = (body.get("repo") or "").strip()
    if not (pattern and scope and rationale and repo):
        return {"ok": False, "error": "pattern, scope, rationale and repo are required."}
    conf = Confidence(body["confidence"]) if body.get("confidence") else Confidence.MEDIUM
    d = Decision(repo=repo, pattern=pattern, scope=scope, rationale=rationale,
                 origin=Origin.HUMAN, confidence=conf, status=Status.CANDIDATE)
    store.add(d)
    return {"ok": True, "id": d.id}


def update_decision(store, decision_id: str, body: dict) -> dict:
    """Edit a decision's content. Allowed for candidate + canonical; rejected is read-only."""
    from metatron.models import Confidence, Status
    decision = store.get(decision_id)
    if decision is None:
        return {"ok": False, "error": f"No decision with id {decision_id!r} (not found)."}
    if decision.status is Status.REJECTED:
        return {"ok": False, "error": "A rejected decision is read-only."}
    fields = {k: body[k] for k in ("pattern", "scope", "rationale") if body.get(k) is not None}
    if body.get("confidence"):
        fields["confidence"] = Confidence(body["confidence"])
    updated = store.update_fields(decision_id, **fields)
    return {"ok": True, "id": updated.id}
```

- [ ] **Step 4: Add the routes in `server.py` `do_POST`**

Before the `/api/decisions/<id>/<action>` block, add the create route; inside the 4-segment block, add the `update` action:

```python
if segments == ["api", "decisions"]:
    body = self._read_json()
    return self._send_json(api.create_decision(store, body))
```

and within the `len(segments) == 4 and segments[:2] == ["api", "decisions"]` block:

```python
if action == "update":
    body = self._read_json()
    return self._send_json(api.update_decision(store, decision_id, body))
```

- [ ] **Step 5: Run — expect pass**

Run: `uv run pytest tests/test_web_api.py -k "create_decision or update_decision" -v` → PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add metatron/webui/api.py metatron/webui/server.py tests/test_web_api.py
git commit -m "feat(webui): add create + update endpoints for human-authored and edited decisions"
```

### Task D4: API-client methods + `Origin.HUMAN` rendering

**Files:**
- Modify: `metatron/webui/app/api.js` (`createDecision`, `updateDecision`)
- Modify: `metatron/webui/app/ui.jsx:33-41` (`ORIGIN_LABEL`, `ORIGIN_DESC`, `OriginTag` dot color)
- Modify: `metatron/webui/app/views_knowledge.jsx:105` (`ORIGIN_OPTS`)

- [ ] **Step 1: Add the client methods**

```javascript
createDecision(repo, fields) {
  return P("/api/decisions", { repo, ...fields });
},
updateDecision(id, fields) {
  return P(`/api/decisions/${id}/update`, fields);
},
```

- [ ] **Step 2: Render the `human` origin**

In `ui.jsx`, extend the three origin maps so `human` has a label, description, and dot color:

```javascript
const ORIGIN_LABEL = { bootstrap: "Bootstrap", agent_submitted: "Agent-submitted", agent_feedback: "Agent-feedback", human: "Human-authored" };
// ORIGIN_DESC: human: "Authored directly by a human curator"
// OriginTag dot map: human: "var(--emerald)"
```

In `views_knowledge.jsx`, add `"human"` to `ORIGIN_OPTS` so the filter rail can select it.

- [ ] **Step 3: Commit**

```bash
git add metatron/webui/app/api.js metatron/webui/app/ui.jsx metatron/webui/app/views_knowledge.jsx
git commit -m "feat(webui): client methods and rendering for human-authored decisions"
```

### Task D5: Shared `DecisionEditor` validation (extracted logic + test)

**Files:**
- Create: `metatron/webui/app/decision_editor.js` (pure validation helper)
- Create: `metatron/webui/app/decision_editor.test.js`

Extract the form's validation into a plain module so it can be unit-tested (matching the `activity_signature.js` + `.test.js` pattern), keeping the JSX presentational.

- [ ] **Step 1: Write the failing test**

`decision_editor.test.js`:

```javascript
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { validateDecisionForm } = require("./decision_editor.js");

test("requires pattern, scope, and rationale", () => {
  assert.deepStrictEqual(validateDecisionForm({ pattern: "", scope: "app", rationale: "r" }).ok, false);
  assert.strictEqual(validateDecisionForm({ pattern: "p", scope: "app", rationale: "r" }).ok, true);
});

test("trims whitespace-only fields to invalid", () => {
  assert.strictEqual(validateDecisionForm({ pattern: "  ", scope: "app", rationale: "r" }).ok, false);
});
```

- [ ] **Step 2: Run — expect failure**

Run: `node --test metatron/webui/app/decision_editor.test.js` → FAIL (module not found).

- [ ] **Step 3: Implement the helper**

`decision_editor.js`:

```javascript
"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.DecisionEditorLogic = api;
})(this, function () {
  function validateDecisionForm(f) {
    const need = ["pattern", "scope", "rationale"];
    const missing = need.filter((k) => !((f[k] || "").trim()));
    return { ok: missing.length === 0, missing };
  }
  return { validateDecisionForm };
});
```

(Confirm the UMD shape against `activity_signature.js`'s actual export idiom and match it exactly — that file is the canonical pattern in this app.)

- [ ] **Step 4: Run — expect pass**

Run: `node --test metatron/webui/app/decision_editor.test.js` → PASS.

- [ ] **Step 5: Wire it into `index.html`**

Add `<script src="decision_editor.js"></script>` alongside the other app scripts in `index.html`, before `views_knowledge.jsx`.

- [ ] **Step 6: Commit**

```bash
git add metatron/webui/app/decision_editor.js metatron/webui/app/decision_editor.test.js metatron/webui/app/index.html
git commit -m "feat(webui): add validated decision-form logic for the shared editor"
```

### Task D6: `DecisionEditor` component — edit + add in the UI

**Files:**
- Modify: `metatron/webui/app/views_knowledge.jsx` (`DecisionEditor` component; `CurationView` header "+ Add decision"; edit affordance on `CandidateCard`)
- Possibly modify: `metatron/webui/app/ui.jsx` / `app.jsx` (edit affordance in the decision drawer)

- [ ] **Step 1: Build the `DecisionEditor` component**

A controlled form with fields pattern (textarea), scope (input), rationale (textarea), confidence (select: low/medium/high), Save/Cancel. Gate Save on `DecisionEditorLogic.validateDecisionForm(form).ok`. On save: add-mode → `MetatronAPI.createDecision(repo, form)`; edit-mode → `MetatronAPI.updateDecision(id, form)`. Call a passed `onSaved` to reload the queue/drawer. Style with the existing panel/input classes — do not introduce a new visual language.

- [ ] **Step 2: Add "+ Add decision" to the Curation header**

In `CurationView`'s `SectionTitle` `right` slot, add a button that opens the editor in add-mode (empty form, `repo` from props). On save, `res.reload()` so the new candidate appears.

- [ ] **Step 3: Add an edit affordance to `CandidateCard` (candidate + canonical)**

Add a small "Edit" control (e.g. next to "Inspect") that opens the editor in edit-mode populated from `p`. Show it for candidates here; for canonical decisions, surface the same editor from the decision drawer (`app.jsx`/`ui.jsx`) so already-served decisions are editable too. On save, reload the relevant view.

- [ ] **Step 4: Verify in the running UI**

- Click "+ Add decision", fill the form, save → the new candidate appears in the queue with the **Human-authored** origin tag and starts as a candidate (not canonical).
- Edit a candidate's pattern/rationale, save → the card text updates; `status`/`triage` unchanged.
- Edit a canonical decision from the drawer → content updates, it stays canonical.
- Confirm a rejected decision offers no edit (or the editor surfaces the read-only error).

- [ ] **Step 5: Commit**

```bash
git add metatron/webui/app/views_knowledge.jsx metatron/webui/app/ui.jsx metatron/webui/app/app.jsx
git commit -m "feat(webui): shared editor to author and edit decisions inline"
```

---

## Final verification (per PR)

Before opening each PR:

- [ ] Backend: `uv run pytest -q` (whole suite green; no regressions).
- [ ] Frontend logic: `npm test` (all `node:test` files pass).
- [ ] Manual: exercise the PR's UI flows in `uv run metatron ui` per the verify steps above.
- [ ] Confirm commit/PR text is neutral and third-person (public repo rule).
- [ ] Open the PR against `main`; keep it scoped to its item set.

## Suggested PR order

A → B → C → D. A is independent polish; B and C are independent of each other; D is independent but largest. C's backend change (`decision_ids`) is self-contained. Each can merge on its own, but this order ships value fastest and keeps diffs small.
