---
type: Metatron Decision
scope: metatron/version.py
confidence: high
source_refs:
  - metatron/version.py
  - docs/designs/2026-06-09-version-and-update-notice.md
---

## Pattern
Anything that touches the network from a CLI or server path must be fail-silent
and bounded: short timeout, broad exception swallowing at the orchestrator,
throttled via an on-disk cache (24h for the update check), disable-able by env
var (`METATRON_NO_UPDATE_CHECK`). Request-serving paths use `cache_only=True` —
they read the cache but never fetch, so a single-threaded server can't block on
an external service. Only CLI/startup paths warm the cache.

## Rationale
Metatron is an on-prem tool that must work offline and air-gapped; a network
nicety (like the PyPI update notice) can never break, slow, or block a command.
The cache-only server path exists because the stdlib web server is
single-threaded — one hung fetch would freeze the UI. Tests inject the fetch
function; nothing in the test suite hits the live network.
