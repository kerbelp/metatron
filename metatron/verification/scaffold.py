"""Scaffold contract skeletons: the canonical template and `verification new`."""
from __future__ import annotations

from pathlib import Path

from metatron.verification.schema import OKF_TYPE

TEMPLATE = f"""---
type: {OKF_TYPE}
scope: {{scope}}
confidence: medium
source_refs: []
runner: local-shell
---

## Assumptions
- Pre-existing state the run verifies before setup (services, env vars).

## Setup
    # commands that prepare state; non-zero exit aborts the contract

## Checks
### A meaningful behavior  [tags: smoke, critical-path]
Action:
    # a shell command whose exit/stdout/stderr the assertions check
Expect:
- exit 0
- stdout contains SOMETHING

## Failure Means
- What a red check above implies about which subsystem is at fault.

## Teardown
    # commands that always run to restore state
"""


def template(scope: str = "<scope>") -> str:
    return TEMPLATE.format(scope=scope)


def scaffold_new(target_dir: Path, slug: str, scope: str,
                 source_ref: str | None = None) -> Path:
    """Write a draft contract at ``target_dir/slug.md``. Never overwrites."""
    target = Path(target_dir) / f"{slug}.md"
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = template(scope)
    if source_ref:
        body = body.replace("source_refs: []", f"source_refs:\n  - {source_ref}")
    target.write_text(body, encoding="utf-8")
    return target
