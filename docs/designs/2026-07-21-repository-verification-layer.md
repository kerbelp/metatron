# Repository Verification Layer (RVL)

**Date:** 2026-07-21 (rev. 2026-07-22) · **Status:** phase 1 implemented
(executable-first CLI + read-only MCP); `--judge` mode and the mirror-typed
serving remain phase 2

## Problem

Metatron captures how an agent should *think* about a repository — intent,
invariants, architecture, conventions — as curated OKF decisions. It says
nothing about how to *prove a change works in execution*.

Today an agent finishes a change, writes unit tests, and then — when a human or
the next agent asks "how do I actually run this?" — invents ephemeral operational
steps in the prompt window: `docker compose up`, migration commands, seed
fixtures, `curl` calls, sample JWTs, expected status codes. None of that is
committed. When the session ends it vanishes, and the next agent rediscovers it
from scratch. This is the same rediscovery problem Metatron already solves for
architectural knowledge, applied to *operational verification* knowledge.

The gap: repositories have no durable, machine-readable, human-reviewed artifact
that answers **"how do we prove this behavior, and what does a failure imply?"**

## Non-goals (explicit scope fence)

This spec deliberately does **not** propose that Metatron:

- **Execute verification in any serving path.** There is no `run_verification`
  MCP tool, no runner behind the request-serving/MCP layer, no sandbox owned by
  Metatron-as-a-service. The MCP and mirror-serving surfaces stay read-only.
  *A developer-invoked `metatron verification run` CLI is in scope* (see the CLI
  section) — it executes in the operator's own shell, foreground, with their own
  privileges, exactly as if they ran the commands or `pytest` by hand. The fence
  is about the trust boundary, not about execution existing at all: nothing an
  agent reaches over the wire, and nothing in a path expected never to block,
  ever executes. See "Why execution stays out of the serving path" below.
- **Let an agent trigger execution.** `verification run` is a human/CI verb, not
  an MCP tool and not something the agent invokes autonomously. A prompt-injected
  or agent-authored contract can never cause code to run; only an operator typing
  the command (or a CI job they configured) can.
- **Close a self-healing loop.** "Re-run until green, mutating code autonomously"
  is the unsupervised-mutation loop held back under CLAUDE.md scope discipline.
  RVL produces the artifact and a report a human reads; the agent's own loop is
  out of scope.
- **Introduce a new root namespace.** No `.repo/`, no `migrate-repo-layout`. The
  KB directory default is `context/` (legacy `metatron/` recognized), settled;
  verification lives inside it. Reopening the naming decision buys no capability.
- **Auto-author canonical artifacts.** Nothing crosses the canonical boundary
  without human review (CLAUDE.md, Core principle). See lifecycle below.

## Design

### 1. Verification is a new OKF artifact type, served through the existing machinery

A verification contract is a git-tracked OKF markdown file with a declared
`type: Metatron Verification` in frontmatter, living under the existing status
directories alongside decisions:

```
context/
├── decisions/                 # canonical decisions (existing)
│   └── <slug>.md
├── candidate/                 # staged proposals (existing)
│   └── <slug>.md
└── verification/              # NEW: canonical verification contracts
    └── <slug>.md
```

`verification/` is a *sibling status class* to `decisions/`, not a new root. It
reuses:

- the same **frontmatter/scope model** (`scope:` binds a contract to a subsystem,
  exactly as decisions bind);
- the same **reserved-filename discipline** (`index.md`, `log.md` skipped;
  untyped strays never imported — `reserved-files-never-become-decisions`);
- the same **mirror import/export** path (`metatron mirror`), treating
  `type: Metatron Verification` as a recognized OKF type;
- the same **selection/serving** path — this is the load-bearing choice below.

### 2. Serving: selection, not a monolith

Paper 2's confirmed result (RESULTS-06): *selection beats volume.* A single
monolithic `testing.md` read into a context window crowds out task reasoning the
same way the FILE arm did — it was numerically **below** no-context baseline
while paying the most tokens. SHARD (index + only the relevant shard) was best on
gold-hit and 3× cheaper.

Therefore verification contracts are **scoped and served on demand**, one per
subsystem/feature, indexed like decisions — never concatenated into one file an
agent must wade through. An agent working on auth pulls the auth verification
contract, not the billing one. This is the whole reason to build it inside
Metatron rather than as a loose `docs/testing.md` convention.

### 3. Contract format

OKF frontmatter + explicit section headings. The parser keys off headings; the
body stays human-readable and diff-friendly.

```markdown
---
type: Metatron Verification
scope: services/auth
confidence: high
source_refs:
  - context/candidate/oauth-login.md
  - services/auth/login.py
runner: docker-compose        # advisory: which agent/CI runner this assumes
---

## Assumptions
Pre-existing state the agent verifies before setup:
- PostgreSQL on `localhost:5432`, Redis on `localhost:6379`
- Env: `JWT_SECRET` set

## Setup
    npm run db:migrate
    npm run db:seed -- --fixture=auth_users

## Checks
### Successful login returns a bearer token  [tags: smoke, critical-path]
Action:
    curl -s -X POST localhost:3000/api/v1/auth/login \
      -d '{"email":"user@example.com","password":"Correct123!"}'
Expect:
- exit 0
- stdout jsonpath $.tokenType == Bearer
- stdout jsonpath $.accessToken exists

### Wrong password is rejected  [tags: security, regression]
Action:
    curl -s -X POST localhost:3000/api/v1/auth/login \
      -d '{"email":"user@example.com","password":"wrong"}'
Expect:
- exit 0
- stdout jsonpath $.error.code == INVALID_CREDENTIALS

## Failure Means
- happy path missing a token → seed hash mismatch or missing user; `JWT_SECRET` unset.
- wrong password returning a token → auth middleware not rejecting bad credentials.
- curl exit ≠ 0 → gateway/port 3000 down; setup did not complete.

## Teardown
    npm run db:clean
```

**The `## Failure Means` section is the differentiated contribution.** No existing
tool (Postman, pytest, Playwright, Bruno) encodes *what a failure implies about
which subsystem*. It is a curated decision about failure modes — the same kind of
distilled operational judgment Metatron already stores for architecture. It is
what lets a reading agent route a red check to the right fix instead of guessing.

Assertion tiers the runner recognizes, kept minimal and evaluated against a
check's captured exit code / stdout / stderr: `exit <code>`; `contains` and
`matches` (regex) over stdout/stderr; `jsonpath <path> == <value>` / `jsonpath
<path> exists` over stdout parsed as JSON; and a `shell <command>` escape hatch
(passes iff exit 0). `stdout` is the default stream. Over the MCP surface these
are *declarations the agent evaluates* in its own sandbox; only `metatron
verification run` executes them (operator/CI — see §6).

### 4. Lifecycle: same human gate as decisions

Verification contracts follow the identical `review_gate` policy already in
`metatron.toml` (`2026-07-14-review-gate`):

- **`pr` (default):** an agent drafts the contract directly under
  `verification/` on a working branch; the reviewed pull request that lands it is
  the curation act.
- **`candidates`:** the agent stages the draft under `candidate/` (a verification
  candidate is just a candidate with `type: Metatron Verification`); a human
  promotes it with a reviewed `git mv`.

Either way the invariant holds: **a human placing or approving the file into
`verification/` is the curation act.** An agent-authored contract is a proposal,
never self-canonical — exactly as for decisions. This is the single most
important correction to the external draft, whose self-healing loop had agents
writing canonical contracts with no human in the path.

### 5. MCP surface: read-only

`mcp_server/service.py` (logic) + `server.py` (transport) gain, per
`mcp-logic-separate-from-server`:

- `get_verification(scope, tags=[])` → returns the parsed contract(s) matching a
  scope, structured as JSON (assumptions, setup, checks, expected assertions,
  failure-means, teardown). Selection-ranked like decision serving.
- `get_verification_template()` → returns the canonical skeleton so an agent
  drafts in-format.

There is intentionally **no `write_verification` and no `run_verification` MCP
tool.** Writing goes through the file/PR gate like all curation. Execution stays
in the caller's sandbox.

### 6. Why execution stays out of the serving path (and where it is allowed)

Metatron runs against private codebases with an assumed on-prem, offline,
air-gapped posture; "your source never leaves the machine" is a stated guarantee
(`extraction-structural-signals-only`), and network/CLI paths are required to be
fail-silent and bounded (`network-checks-fail-silent`). The danger is not
execution as such — it is execution reachable by an untrusted caller or sitting
in a path that must never block. A primitive that let the **MCP/serving layer**
pipe markdown-defined shell/Docker commands into a runner would:

- turn any writable `context/` file (or a prompt-injected candidate) into an
  arbitrary-code-execution vector reachable *over the wire* by any agent;
- put a long-running, side-effecting subprocess in a request-serving path that is
  supposed to never block.

So the serving surfaces (MCP tools, mirror import/export, the request path) never
execute. What *is* allowed is a **developer-invoked CLI** — `metatron
verification run` — which is a different trust boundary entirely: a foreground
process the operator starts themselves, in their own shell, with their own
privileges, on contracts they can read first. That is identical in trust to the
operator running the commands by hand or wiring them into their CI, which they
could always do. The two rules that keep the fence honest:

1. **No serving-path execution.** Nothing an agent reaches over MCP, and nothing
   in a never-block path, ever runs a contract. `run` is not an MCP tool.
2. **Human/CI in the trigger.** Only an operator (or a CI job they configured)
   invokes `run`. An agent-authored or prompt-injected contract is inert until a
   human chooses to execute it — the same human gate that guards canonicalization
   guards execution.

Metatron's durable role stays the curated, selectively-served *artifact* plus the
"Failure Means" interpretation of a red result. The runner is a thin,
operator-owned convenience over that artifact — not a CI engine, not a service.

## CLI

Mirrors existing `metatron context` / `metatron mirror` verbs. Every verb except
`run` is read/scaffold-only; `run` executes in the operator's own shell (see §6).

### Authoring verbs (read / scaffold — never execute)

- `metatron verification setup` — one-time initialization. Writes an onboarding
  instruction into **`AGENTS.md`** ("after finishing a testable feature, author a
  verification contract under `context/verification/` describing how to prove it
  works and what a failure implies; draft via the `review_gate`, never
  self-canonical") and drops a **worked example contract** into
  `context/verification/` (or `context/candidate/` per gate) as a copy-and-adapt
  reference. Idempotent: re-running updates the onboarding block in place and
  leaves an existing example untouched. This is the authoring half of RVL —
  applying the paper's "author context at the moment of most context" lesson to
  verification: the agent that just built the feature is its strongest author.
- `metatron verification template` — print the canonical skeleton to stdout (CLI
  twin of the `get_verification_template()` MCP tool).
- `metatron verification new --scope services/auth [--from candidate/oauth-login.md]`
  — scaffold a draft contract (into `candidate/` or `verification/` per
  `review_gate`), inferring happy-path/edge-case stubs from the referenced
  candidate and in-scope decisions. Never promotes.
- `metatron verification audit` — read-only lint: contracts whose `source_refs`
  point at deleted paths, contracts with no scoped decision, reserved-name
  collisions, malformed assertion blocks. Reports; changes nothing.

### `metatron verification run` — the operator/CI runner

Executes contracts and prints a report shaped like a unit-test run (per-check
PASS/FAIL, timing, a summary line), optionally writing machine-readable output.
This is a **developer/CI verb**, foreground, never an MCP tool, never
agent-invoked (§6).

```
metatron verification run [--scope <path>] [--tags smoke,critical-path]
                          [--report text|json|junit] [--out report.xml]
                          [--judge]          # opt-in LLM-judged mode (phase 2)
                          [--dry-run]        # print the plan; execute nothing
```

Behavior:

- **Selection, not everything.** With no `--scope` it runs all canonical
  contracts; `--scope`/`--tags` narrow to a subsystem or check class — the same
  selective serving the layer is built on (Paper 2). CI runs the `smoke` +
  `critical-path` tags on every PR; a nightly job runs the full set.
- **Per contract:** verify `## Assumptions`, run `## Setup`, evaluate each
  `## Checks` action against its `Expect` assertions (status/exit, substring,
  JSONPath, regex, shell escape hatch), always run `## Teardown` (even on
  failure). Exit non-zero if any check fails, so it drops into CI unchanged.
- **`## Failure Means` in the report.** This is the differentiator: a red check
  prints its curated failure interpretation next to it, so the operator (or the
  agent reading the report) routes the failure to the right subsystem instead of
  guessing. No other runner does this.
- **`--dry-run`** resolves and prints the ordered plan (setup → checks →
  teardown) and the resolved assertions without executing — safe to run against
  an untrusted contract to read exactly what it *would* do before allowing it.

**Execution modes — decided:**

- **Phase 1, executable-first (default, ship this).** Deterministic evaluation of
  the declared assertions. Cheap, offline, no model in the loop, drops straight
  into CI and pre-commit. This is the whole first milestone.
- **Phase 2, `--judge` (opt-in, later).** For invariants no assertion can express
  ("the error copy stays user-neutral", "the migration is reversible"), a model
  judges the check against the contract's intent. Explicitly opt-in and clearly
  labeled non-deterministic; never the default; never a merge gate on its own.

A contract mixing both — executable checks plus a couple of `judge:`-flagged
invariants — runs the deterministic ones always and the judged ones only under
`--judge`.

## Interaction with existing invariants (checklist)

| Invariant | How RVL respects it |
|---|---|
| Human-gated canonical boundary | Contracts land via the same `review_gate` (pr/candidates) as decisions; no self-promotion. |
| Reserved files never become decisions | `type: Metatron Verification` required; `index.md`/`log.md` skipped; untyped strays ignored. |
| Source never leaves the machine | Contracts are local markdown; `run` executes in the operator's on-prem shell; nothing ships off-box. |
| Serving path never executes | No `run_verification` MCP tool; MCP/mirror/request paths are read-only. `run` is a foreground operator/CI verb outside every serving path. |
| Execution is human/CI-gated | Only an operator (or a CI job they set up) invokes `run`; agent-authored or injected contracts are inert until a human chooses to execute. |
| Network/CLI fail-silent & offline | No new network path in serving; `run` is offline-capable and operator-initiated, not a background service. |
| MCP logic separate from server | Parsing/selection in `service.py`; `server.py` only wires transport. |
| Selection beats volume (Paper 2) | Scoped per-subsystem contracts served on demand; never a monolithic `testing.md`. |
| SQLite behind storage interface | Verification contracts are files-first OKF; DB mirror is a derived serving index, same as decisions. |

## Rollout & deliverables (end to end)

Ship the feature and its explanation together. Ordered so each artifact grounds
the next; nothing marketing-facing goes live before the feature is real.

1. **Build — CLI + MCP.** Phase-1 `verification setup / template / new / audit /
   run` (executable-first), `get_verification` / `get_verification_template` MCP
   tools (read-only), OKF parser recognizing `type: Metatron Verification`, mirror
   import/export support. Each PR small, tested (pytest), neutral commit text.
2. **Docs (in-repo).** `docs/verification.md` — the operator-facing guide:
   what a contract is, the authoring workflow (`setup` → agent drafts → review
   gate), the `run` workflow (local + CI), the assertion tiers, and the security
   boundary (why `run` is CLI/CI-only, never MCP). Cross-linked from the README
   feature list once built.
3. **Examples (in-repo).** `docs/examples/verification/` — at least the worked
   auth contract from §3 plus one non-HTTP example (a CLI tool or a library
   invariant) so the format reads as general, not HTTP-only. `setup` ships the
   auth one as its bundled reference.
4. **Blog (getmetatron.com).** A post — *"Verification contracts: teaching your
   repo how to prove itself"* — in the house blog template: the rediscovery
   problem, the contract + "Failure Means" idea, the author-at-most-context
   lesson tied back to the context-inheritance study, and the honest fence (why
   Metatron serves the artifact but the operator runs it). PRODUCT/ENGINEERING
   tag. **Staged on a branch, published only when the feature ships.**
5. **Socials (marketing/social).** An X thread + long-form article in
   `marketing/social/verification-contracts/`, house pixel-art figures
   (contract anatomy; the setup→draft→review→run loop; a sample `run` report with
   "Failure Means" routing a red check). Drafts only — the founder publishes on
   launch. Numbers/claims frozen to what actually ships; no vaporware metrics.

The blog and socials are written against this spec now (so the narrative is ready)
but gated behind the build — consistent with neutral, non-vaporware public
messaging.

## Research note (separate track, not gating this build)

There is a plausible follow-up study to RCL: *does a structured verification layer
(esp. "Failure Means") improve an agent's ability to reach a correct fix?* It is
harder to measure than gold-hit — end-to-end verification needs live infra per
episode, so resolve-rate is the natural proxy and the eval is heavier. Recommended
order: build the artifact inside Metatron, gather anecdotal signal, then design the
study. Do not couple the feature to the paper; the feature stands on its own.

## Open questions

- Should a verification contract be a distinct type or a `## Verification` block
  *on* an existing decision? Distinct type chosen here (independent scope, lifecycle,
  and selection), but a block-on-decision variant is worth prototyping for tightly
  coupled cases.
- Assertion DSL surface: how much beyond status/substring/jsonpath/regex before it
  becomes a fragile mini-language? Start minimal; let real contracts pull scope.
- Template distribution: ship via the existing `okf_skills` skill set so an LLM can
  author a contract without the CLI, mirroring `context-okf-llm-ingest`.
