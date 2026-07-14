---
type: Metatron Decision
scope: release
confidence: medium
---

## Pattern
After pushing a release tag, verify the publish end-to-end: wait for the
workflow, confirm the new version on PyPI's JSON API, then upgrade a real
install with `uv tool upgrade getmetatron --no-cache` — the `--no-cache` flag
matters, and PyPI's JSON API may lag the workflow by a minute.

## Rationale
uv caches package-index metadata, so immediately after publishing,
`uv tool upgrade` reports "Nothing to upgrade" against the stale index and the
release looks broken when it is not. The same staleness affects users in the
minutes after a release.
