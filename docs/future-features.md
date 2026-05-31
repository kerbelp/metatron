# Future features (deferred)

Three related-but-distinct ideas around **measuring and improving prior quality**.
They are easy to conflate, so this doc keeps them separate. They run from "safe,
in-scope tooling" to "explicitly deferred product feature." The boundary that
matters is **automatic actuation onto the canonical set**: keep a human between
any signal and any mutation of priors until quality is proven.

| | What it is | Touches priors? | Measures |
|---|---|---|---|
| **A. Eval harness** | Human labels *priors* useful/wrong/noise, offline | No | Extraction quality |
| **B. Helpfulness feedback** | Human rates each *served query*, recorded | Yes (human-gated) | End-to-end usefulness |
| **C. Self-improving loop** | System auto-adjusts priors from signals | Yes (automatic) | — |

## A. Offline prior-quality evaluation harness

- **What:** internal/dev tooling. Ingest across several real repos, sample the
  extracted priors, and have a human label each **useful / wrong / noise**.
  Produces a quality score for the extractor — especially the **confidently-wrong
  rate**, which is the trust-killer (an agent following a wrong prior is worse
  than no tool).
- **Touches the product?** No. Measurement only; it never writes back to the store.
- **Measures:** extraction quality *in isolation* — "are the priors themselves
  good?" — independent of retrieval.
- **Why:** answers "is the extractor reliable / where is it weak?" It is also the
  **prerequisite** for ever safely building (C): you cannot auto-optimize a metric
  you cannot trust.
- **Status:** in scope as **dev tooling** (human judges, offline, no mutation, agents
  never touch it). Not a shipped product feature.
- **Guardrail:** nothing it produces may write back into priors automatically.

## B. Human helpfulness feedback (per query)

- **What:** in the Observability UI, a "was this helpful?" control next to each
  served query; the human's rating is recorded.
- **Touches the product?** Yes — it is a **human-gated feedback loop**.
- **Measures:** end-to-end usefulness *in practice* (extraction × retrieval × the
  agent's use). The most direct signal for "is Metatron valuable?"
- **Design cautions (if built):**
  - Record helpfulness as its **own** per-prior signal (helpful / not-helpful
    tally). Do **not** overload `confidence`, which means "how strongly the signals
    support this prior" at extraction time — overloading it makes the field mean two
    things and trustworthy as neither.
  - **"Helpful here" ≠ "better everywhere":** a prior can help one query and be noise
    in another. Don't raise *global* quality from one in-context thumbs-up.
  - Keep the human in the loop: feedback **informs curation**; it must not
    auto-promote or auto-rank without review (that is drift toward C).
- **Status:** deferred. It is the **human-gated cousin of (C)** — safer than C, but
  still a feedback loop, not mere measurement.

## C. Self-improving loop (automatic)

- **What:** the system automatically uses signals (usage, agent self-reported
  helpfulness, outcomes) to promote / demote / refine priors over time — RL-flavored,
  closed loop, no human in the loop.
- **Touches the product?** Yes, automatically and continuously.
- **Status:** **explicitly deferred** (see CLAUDE.md scope discipline). The risky part
  is *unsupervised mutation* — amplifying confidently-wrong or stale priors with
  nobody watching.
- **Prerequisites:** (A) a trustworthy quality metric, and likely (B)'s human-rated
  data as ground truth, before this is safe to attempt.

## Related open problems

- **Staleness / decay:** priors are extracted at a point in time; codebases drift.
  A curated prior can become *confidently outdated* — the same trust-kill as
  confidently wrong, but silent and later. There is no re-validation mechanism yet.
- **Curation fatigue:** the human curation gate only stays sustainable if
  extraction signal-to-noise is high. Noisy extraction makes curation a chore and
  the loop breaks — another reason (A) gates everything else.
