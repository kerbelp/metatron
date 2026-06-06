# Future features (deferred)

Three related-but-distinct ideas around **measuring and improving decision quality**.
They are easy to conflate, so this doc keeps them separate. They run from "safe,
in-scope tooling" to "explicitly deferred product feature." The boundary that
matters is **automatic actuation onto the canonical set**: keep a human between
any signal and any mutation of decisions until quality is proven.

| | What it is | Touches decisions? | Measures |
|---|---|---|---|
| **A. Eval harness** | Human labels *decisions* useful/wrong/noise, offline | No | Extraction quality |
| **B. Helpfulness feedback** | Human rates each *served query*, recorded | Yes (human-gated) | End-to-end usefulness |
| **C. Self-improving loop** | System auto-adjusts decisions from signals | Yes (automatic) | — |

**C is now partially built (2026-06-03):** a bounded slice auto-weights serve
*ordering* among canonical decisions from helpfulness ratings. Mutation across the
canonical boundary (promote/demote/reject) is still human-gated. See section C.

## A. Offline decision-quality evaluation harness

- **What:** internal/dev tooling. Ingest across several real repos, sample the
  extracted decisions, and have a human label each **useful / wrong / noise**.
  Produces a quality score for the extractor — especially the **confidently-wrong
  rate**, which is the trust-killer (an agent following a wrong decision is worse
  than no tool).
- **Touches the product?** No. Measurement only; it never writes back to the store.
- **Measures:** extraction quality *in isolation* — "are the decisions themselves
  good?" — independent of retrieval.
- **Why:** answers "is the extractor reliable / where is it weak?" It is also the
  **prerequisite** for ever safely building (C): you cannot auto-optimize a metric
  you cannot trust.
- **Status:** in scope as **dev tooling** (human judges, offline, no mutation, agents
  never touch it). Not a shipped product feature.
- **Guardrail:** nothing it produces may write back into decisions automatically.

## B. Human helpfulness feedback (per query)

- **What:** in the Observability UI, a "was this helpful?" control next to each
  served query; the human's rating is recorded.
- **Touches the product?** Yes — it is a **human-gated feedback loop**.
- **Measures:** end-to-end usefulness *in practice* (extraction × retrieval × the
  agent's use). The most direct signal for "is Metatron valuable?"
- **Design cautions (if built):**
  - Record helpfulness as its **own** per-decision signal (helpful / not-helpful
    tally). Do **not** overload `confidence`, which means "how strongly the signals
    support this decision" at extraction time — overloading it makes the field mean two
    things and trustworthy as neither.
  - **"Helpful here" ≠ "better everywhere":** a decision can help one query and be noise
    in another. Don't raise *global* quality from one in-context thumbs-up.
  - Keep the human in the loop: feedback **informs curation**; it must not
    auto-promote or auto-rank without review (that is drift toward C).
- **Status:** deferred. It is the **human-gated cousin of (C)** — safer than C, but
  still a feedback loop, not mere measurement.

## C. Self-improving loop (automatic)

- **What:** the system automatically uses signals (usage, agent self-reported
  helpfulness, outcomes) to promote / demote / refine decisions over time — RL-flavored,
  closed loop, no human in the loop.
- **Touches the product?** Yes, automatically and continuously.
- **Status:** **partially built (2026-06-03)** — see
  `designs/2026-06-03-decision-helpfulness-rating.md`. A **bounded** slice is now live:
  agents rate served decisions 1–10, and a time-decayed, shrunk-to-neutral score
  **auto-reorders which canonical decisions are served first**. The risky part of full
  C — *unsupervised mutation across the canonical boundary* (promote / demote /
  reject) — is **still not built**: the auto-weighting only reorders *within* a scope
  tier and can never cross the canonical boundary. Every promotion/demotion/reject
  stays human-gated, surfaced via the Leaderboard review queue.
- **Prerequisites for going further:** (A) a trustworthy quality metric, and likely
  (B)'s human-rated data as ground truth, before any *unsupervised mutation* is
  attempted. The current slice deliberately stops short of that.

## Related open problems

- **Staleness / decay:** decisions are extracted at a point in time; codebases drift.
  A curated decision can become *confidently outdated* — the same trust-kill as
  confidently wrong, but silent and later. There is no re-validation mechanism yet.
- **Curation fatigue:** the human curation gate only stays sustainable if
  extraction signal-to-noise is high. Noisy extraction makes curation a chore and
  the loop breaks — another reason (A) gates everything else.
