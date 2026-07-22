---
type: Metatron Verification
scope: cli/export
confidence: high
source_refs:
  - src/metatron/cli/export.py
runner: local-shell          # no services needed; plain process invocation
---

## Assumptions
Pre-existing state verified before setup runs:
- A built CLI on `PATH` as `metatron`
- A scratch dir `./_verify` is writable

## Setup
    rm -rf ./_verify && mkdir -p ./_verify

## Checks
### Export writes a well-formed OKF bundle  [tags: smoke, critical-path]
Action:
    metatron export --out ./_verify/bundle
Expect:
- exit 0
- stdout contains wrote
- shell test -f ./_verify/bundle/decisions/index.md

### Every exported decision carries a type  [tags: regression]
Action:
    metatron export --out ./_verify/bundle --format okf
Expect:
- exit 0
- shell ! grep -Lr '^type:' ./_verify/bundle/decisions/*.md

### Refuses to overwrite a non-empty target  [tags: safety]
Action:
    metatron export --out ./_verify/bundle
Expect:
- exit 2
- stderr contains refusing to overwrite

## Failure Means
- non-zero exit on the happy path -> serializer crash or unwritable target; check
  the scratch dir permissions before suspecting the exporter.
- a decision missing `type:` -> the OKF writer dropped frontmatter; this breaks
  round-trip import (`metatron mirror import` silently skips untyped strays).
- exit 0 on the overwrite case -> the safety guard regressed; a real bundle could
  be clobbered in place. Treat as release-blocking.

## Judged invariants  [--judge]
- judge: The `--help` text for `export` names every format `--format` accepts and
  does not advertise a format the command rejects. (No assertion can phrase this;
  a model reads `metatron export --help` and judges it against the contract.)

## Teardown
    rm -rf ./_verify
