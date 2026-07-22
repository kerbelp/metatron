# Verification contracts

> Phase 1 (executable-first) is implemented: the `metatron verification` CLI and
> the read-only `get_verification` / `get_verification_template` MCP tools. The
> `--judge` LLM-evaluated mode is a phase-2 hook (skipped until a provider is
> wired). Design: `docs/designs/2026-07-21-repository-verification-layer.md`.

A **verification contract** is a git-tracked OKF markdown file that answers one
question a repository otherwise never records: *how do we prove this behavior
works, and what does a failure imply?* Metatron already captures how an agent
should think about a codebase (decisions); a verification contract captures how to
prove a change runs — the setup, the checks, the expected results, and — the part
no test runner encodes — what each failure means about which subsystem.

Contracts live beside decisions and flow through the same machinery:

```
context/
├── decisions/            # canonical decisions
├── candidate/            # staged proposals
└── verification/         # canonical verification contracts
    └── <slug>.md
```

See `docs/examples/verification/` for two worked contracts: an HTTP service
(`auth-login.md`) and a CLI/library invariant (`export-cli.md`).

## The two halves: author, then run

### 1. Authoring (read/scaffold — never executes)

Run once per repo to wire the workflow in:

```
metatron verification setup
```

This writes an onboarding instruction into `AGENTS.md` — *after finishing a
testable feature, author a verification contract under `context/verification/`* —
and drops a worked example as a copy-and-adapt reference. From then on, the agent
that just built a feature (its strongest possible author, with the most context it
will ever have) drafts the contract as part of finishing the work.

Drafting follows the same **review gate** as decisions (`metatron.toml`
`review_gate`): the agent proposes under `candidate/` or on a branch; a human
placing or approving the file into `verification/` is the curation act. An
agent-authored contract is never self-canonical.

Supporting authoring verbs, all read-only:

- `metatron verification template` — print the canonical skeleton.
- `metatron verification new --scope services/auth [--from candidate/oauth-login.md]`
  — scaffold a draft from a candidate and in-scope decisions.
- `metatron verification audit` — lint for dangling `source_refs`, contracts with
  no scoped decision, reserved-name collisions, malformed assertions.

### 2. Running (operator/CI — executes locally)

```
metatron verification run [--scope services/auth] [--tags smoke,critical-path]
                          [--report text|json|junit] [--out report.xml]
                          [--dry-run] [--judge]
```

`run` verifies assumptions, runs setup, evaluates each check's assertions, and
always runs teardown — printing a report shaped like a unit-test run. It exits
non-zero on any failure, so it drops into CI unchanged. Selection is first-class:
no flag runs everything; `--scope`/`--tags` narrow to a subsystem or check class.

The differentiator shows up in the report: a red check prints its **Failure
Means** interpretation next to it, so you route the failure to the right fix
instead of guessing.

`--dry-run` prints the ordered plan and resolved assertions **without executing** —
safe to run first against any contract to read exactly what it would do.

## Assertion tiers

Checks declare expected results the runner evaluates:

Each `Action` runs as a shell script; assertions evaluate against its captured
exit code, stdout, and stderr:

| Tier | Example |
|---|---|
| exit code | `exit 0` |
| substring | `stdout contains wrote`, `stderr contains refusing` |
| regex | `stdout matches ^ok$`, `stderr matches timeout after \d+s` |
| JSONPath (stdout parsed as JSON) | `stdout jsonpath $.tokenType == Bearer`, `stdout jsonpath $.accessToken exists` |
| shell escape hatch (passes iff exit 0) | `shell test -f ./out/index.md` |

`stdout` is the default stream for `contains`/`matches`/`jsonpath`, so
`contains wrote` means `stdout contains wrote`.

## Execution modes

- **Executable-first (default).** Deterministic evaluation of the declared
  assertions. Offline, cheap, no model in the loop — the CI/pre-commit path.
- **`--judge` (opt-in, later phase).** For invariants no assertion can express
  ("error copy stays user-neutral", "the migration is reversible"), a model judges
  the check against the contract's intent. Non-deterministic by nature; opt-in;
  never a merge gate on its own.

## Security boundary (why `run` is CLI/CI-only)

Metatron's serving surfaces — the MCP tools, mirror import/export, the request
path — **never execute a contract**. There is no `run_verification` MCP tool. On a
private, on-prem deployment, letting an over-the-wire caller pipe
markdown-defined shell into a runner would be an arbitrary-code-execution vector,
and a side-effecting subprocess has no place in a path that must never block.

`metatron verification run` is a different trust boundary: a foreground process
**you** start, in your own shell, with your own privileges, on contracts you can
read first — identical in trust to running the commands by hand or wiring them
into your CI. Two rules keep the fence honest: nothing an agent reaches over MCP
ever executes, and only a human (or a CI job they configured) triggers `run`. An
agent-authored or prompt-injected contract is inert until a human chooses to
execute it.

The read-only MCP tools an agent *does* get:

- `get_verification(scope, tags=[])` — the parsed contract(s) for a scope.
- `get_verification_template()` — the skeleton, so an agent drafts in-format.
