"""`metatron verification setup` — wire the authoring workflow into a repo.

Writes a managed onboarding block into ``AGENTS.md`` (so the agent that just built
a feature authors its contract) and drops a runnable worked example. Idempotent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from metatron.config import DEFAULT_CONTEXT_DIR, load_settings, resolve_context_dir
from metatron.verification.schema import OKF_TYPE, VERIFICATION_DIR

_START = "<!-- METATRON:VERIFICATION:START -->"
_END = "<!-- METATRON:VERIFICATION:END -->"
_BLOCK_RE = re.compile(re.escape(_START) + r".*?" + re.escape(_END) + r"\n?", re.DOTALL)

EXAMPLE_SLUG = "example-cli"
# A self-contained, runnable example (no services needed) so `run` works out of
# the box against it. Kept in sync with docs/examples/verification/.
EXAMPLE_CONTRACT = f"""---
type: {OKF_TYPE}
scope: cli/example
confidence: medium
source_refs: []
runner: local-shell
---

## Assumptions
- A POSIX shell with `printf` and `test` on PATH.

## Setup
    mkdir -p ./_verify && printf 'ok\\n' > ./_verify/marker

## Checks
### The marker file is created and readable  [tags: smoke, critical-path]
Action:
    cat ./_verify/marker
Expect:
- exit 0
- stdout contains ok

### A missing file is reported, not silently ignored  [tags: regression]
Action:
    cat ./_verify/does-not-exist
Expect:
- exit 1
- stderr contains No such file

## Failure Means
- exit != 0 on the first check -> setup did not run or the scratch dir is not
  writable; check permissions before suspecting the command.
- the second check passing with exit 0 -> the tool swallows missing-input errors,
  which hides real failures downstream.

## Teardown
    rm -rf ./_verify
"""


def _onboarding_block(kb_name: str) -> str:
    return (
        f"{_START}\n"
        "## Verification contracts\n\n"
        "After finishing a testable feature, author a **verification contract** "
        f"under `{kb_name}/{VERIFICATION_DIR}/` describing how to prove it works "
        "and — in the `## Failure Means` section — what a red check implies about "
        "which subsystem broke. Draft it via the review gate; it is never "
        "self-canonical (a human approving the file is the curation act). Start "
        "from `metatron verification template` or the bundled example. Contracts "
        "are executed by an operator or CI with `metatron verification run` — "
        "never over MCP, never agent-triggered.\n"
        f"{_END}\n"
    )


@dataclass
class SetupResult:
    messages: list[str] = field(default_factory=list)


def _upsert_agents_block(md: Path, block: str, res: SetupResult) -> None:
    if md.exists():
        text = md.read_text(encoding="utf-8")
        match = _BLOCK_RE.search(text)
        if match:
            if match.group(0).rstrip("\n") == block.rstrip("\n"):
                res.messages.append(f"{md} already has the verification block — left as is")
                return
            md.write_text(text[:match.start()] + block + text[match.end():], encoding="utf-8")
            res.messages.append(f"refreshed the verification block in {md}")
            return
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        md.write_text(text + sep + block, encoding="utf-8")
        res.messages.append(f"appended the verification block to {md}")
    else:
        md.write_text("# AGENTS\n\n" + block, encoding="utf-8")
        res.messages.append(f"created {md} with the verification block")


def run_verification_setup(
    target: str | Path = ".",
    *,
    dir_name: str | None = None,
    review_gate: str | None = None,
) -> SetupResult:
    target = Path(target)
    settings = load_settings()
    kb_name = dir_name or settings.context_dir or DEFAULT_CONTEXT_DIR
    gate = review_gate or settings.review_gate or "pr"
    res = SetupResult()

    _upsert_agents_block(target / "AGENTS.md", _onboarding_block(kb_name), res)

    kb = resolve_context_dir(target, dir_name)
    status_dir = VERIFICATION_DIR if gate == "pr" else "candidate"
    dest_dir = kb / status_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    example = dest_dir / f"{EXAMPLE_SLUG}.md"
    if example.exists():
        res.messages.append(f"{example} already exists — left as is")
    else:
        example.write_text(EXAMPLE_CONTRACT, encoding="utf-8")
        res.messages.append(f"wrote worked example {example}")

    res.messages.append(f"review gate: {gate}")
    return res
