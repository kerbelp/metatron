---
type: Metatron Decision
scope: metatron
confidence: high
source_refs:
  - metatron/config.py
  - metatron/mirror/sync_import.py
---

## Pattern
Never hardcode the knowledge-base directory name. Resolve it through
`config.resolve_context_dir(root, configured)`: an explicit configuration
(CLI flag, `METATRON_CONTEXT_DIR`, `metatron.toml` `context_dir`) wins as-is;
otherwise prefer `context/` and fall back to a legacy `metatron/` bundle only
when it actually contains a `candidate/` or `decisions/` status directory.

## Rationale
The bundle root was renamed from `metatron/` to `context/` (the old name
collided with the Python package and with any repo dir named metatron), and
repos onboarded before the rename must keep working unconfigured. A bare
`metatron/` directory without status subdirectories — such as this repo's own
import package — must never hijack resolution.
